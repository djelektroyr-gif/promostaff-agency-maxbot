"""
Сценарии FSM: заказ расчёта (как Telegram-визитка), вопрос менеджеру, анкета в команду.
Состояние в памяти. Уведомления — notify.notify_agency_admins.
"""
from __future__ import annotations

import logging
import random
import re
import time
from typing import Any

from config import (
    APPLICANT_POSITIONS,
    CLIENT_POSITIONS,
    COMPANY_NAME,
    EXPERIENCE_OPTIONS,
    SUPERVISOR_TM_LEAD,
    WEBSITE_URL,
    order_hourly_rates,
)

import visit_card
from funnel_store import funnel_touch_complete
from notify import notify_agency_admins
from shift_pricing import calculate_order_cost, parse_shift_interval

logger = logging.getLogger(__name__)

SESSIONS: dict[int, dict[str, Any]] = {}


SHIFT_STEP_TEXT = (
    "Время работы персонала (одна смена в типичный день)\n\n"
    "Укажите интервал в формате *чч:мм - чч:мм* по времени площадки.\n\n"
    "*Примеры:* `10:00-22:00` (дневная), `22:00-06:00` (через полночь), `08:00-18:00`.\n\n"
    "Дневной тариф: часы с *10:00 до 22:00*. Остальные часы смены — ночные (*+15% к часу*).\n"
    "Если в смене есть хотя бы один ночной час — минимум *8* оплачиваемых часов на человека; "
    "если смена только дневная — минимум *6* часов.\n\n"
    "Дату или период вы уже указали выше — здесь только время смены.\n\n"
    "_Образец:_ `10:00-22:00`"
)


def _new_id() -> int:
    return int(time.time()) % 900_000_000 + random.randint(0, 99_999)


def clear_session(max_uid: int) -> None:
    SESSIONS.pop(max_uid, None)


def _sender_label(sender: dict[str, Any] | None) -> str:
    if not sender:
        return "MAX user"
    un = (sender.get("username") or "").strip()
    if un:
        return f"@{un}"
    uid = sender.get("user_id")
    return f"MAX user_id {uid}" if uid is not None else "MAX user"


def validate_full_name(name: str) -> bool:
    if not name:
        return False
    pattern = r"^[\u0410-\u042f\u0430-\u044f\u0401\u0451A-Za-z\-\s']+$"
    if not re.match(pattern, name):
        return False
    words = name.strip().split()
    return len(words) >= 2


def validate_email(email: str) -> bool:
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))


def validate_phone(phone: str) -> str | None:
    clean = re.sub(r"\D", "", phone)
    if len(clean) == 11 and clean[0] in ("7", "8"):
        return "+7" + clean[1:]
    if len(clean) == 10 and clean[0] == "9":
        return "+7" + clean
    return None


def validate_inn(text: str) -> bool:
    d = re.sub(r"\D", "", (text or "").strip())
    return len(d) in (10, 12)


def validate_metro(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if t == "0":
        return True
    return len(t) >= 2


def total_staff_in_shift(staff_counts: dict | None) -> int:
    if not staff_counts:
        return 0
    return sum(int(v) for v in staff_counts.values() if int(v) > 0)


def recommended_supervisor_count(total_people: int) -> int:
    if total_people < 2:
        return 0
    if total_people < 5:
        return 1
    return (total_people + 4) // 5


def merged_staff_for_pricing(data: dict[str, Any]) -> dict[str, int]:
    staff = {k: int(v) for k, v in (data.get("staff_counts") or {}).items() if int(v) > 0}
    sv = int(data.get("supervisor_count") or 0)
    if sv > 0:
        staff[SUPERVISOR_TM_LEAD] = sv
    return staff


def _image_ref_from_body(message_body: dict[str, Any] | None) -> str | None:
    if not message_body:
        return None
    raw = message_body.get("attachments")
    if raw is None and isinstance(message_body.get("attachment"), dict):
        raw = [message_body["attachment"]]
    if not isinstance(raw, list):
        return None
    for a in raw:
        if not isinstance(a, dict):
            continue
        t = (a.get("type") or "").lower()
        if t not in ("image", "photo", "picture", "file"):
            continue
        p = a.get("payload")
        if isinstance(p, dict):
            for key in ("url", "photo_url", "small_url", "medium_url", "token"):
                v = p.get(key)
                if v:
                    return str(v)
        if isinstance(p, str) and p:
            return p
    return None


VAC_FROM_KEY = {
    "vac_apply_helper": "Хелпер",
    "vac_apply_loader": "Грузчик",
    "vac_apply_promoter": "Промоутер",
    "vac_apply_cloakroom": "Гардеробщик",
    "vac_apply_parking": "Парковщик",
    "vac_apply_hostess": "Хостес",
    "vac_apply_supervisor": "Супервайзер",
}


def start_order(max_uid: int) -> dict[str, Any]:
    clear_session(max_uid)
    SESSIONS[max_uid] = {"flow": "order", "step": "event_type", "data": {}}
    return {
        "text": (
            "*Заказ расчёта стоимости*\n\n"
            "Укажите тип мероприятия (выставка, концерт, корпоратив и т.д.).\n\n"
            "_Образец:_ `Корпоратив, 200 гостей`"
        ),
        "format": "markdown",
        "attachments": visit_card.back_to_main_keyboard(),
    }


def start_question(max_uid: int) -> dict[str, Any]:
    clear_session(max_uid)
    SESSIONS[max_uid] = {"flow": "question", "step": "text", "data": {}}
    return {
        "text": (
            "*Сообщение менеджеру*\n\n"
            "Напишите вопрос одним сообщением — мы ответим в рабочее время."
        ),
        "format": "markdown",
        "attachments": visit_card.back_to_main_keyboard(),
    }


def start_join(max_uid: int) -> dict[str, Any]:
    clear_session(max_uid)
    SESSIONS[max_uid] = {"flow": "join", "step": "position_pick", "data": {}}
    return {
        "text": "Выберите желаемую должность:",
        "format": "markdown",
        "attachments": visit_card.join_applicant_pick_keyboard(),
    }


def join_from_vacancy(max_uid: int, payload: str) -> dict[str, Any] | None:
    title = VAC_FROM_KEY.get(payload)
    if not title:
        return None
    clear_session(max_uid)
    SESSIONS[max_uid] = {"flow": "join", "step": "full_name", "data": {"position": title}}
    return {
        "text": (
            f"*Анкета*\n\n"
            f"Должность: *{title}*\n\n"
            "Укажите ваше полное ФИО.\n\n"
            "_Образец:_ `Иванов Иван Иванович`"
        ),
        "format": "markdown",
        "attachments": visit_card.back_to_main_keyboard(),
    }


def _format_order_plain(data: dict[str, Any], order_id: int, who: str) -> str:
    staff = merged_staff_for_pricing(data)
    parsed = parse_shift_interval(data.get("shift_time", ""))
    details, total, meta = calculate_order_cost(staff, order_hourly_rates(), parsed)
    shift_line = data.get("shift_time") or "—"
    if meta.get("shift_desc"):
        shift_line = f"{shift_line} ({meta['shift_desc']})"
    inn = (data.get("company_inn") or "").strip() or "—"
    co = (data.get("company_name") or "").strip() or "—"
    return (
        f"Новая заявка на расчёт #{order_id}\n"
        f"================================\n\n"
        f"От: {who}\n\n"
        f"Тип: {data.get('event_type', '—')}\n"
        f"Город: {data.get('city', '—')}\n"
        f"Дата / период: {data.get('event_date', '—')}\n"
        f"Время смены: {shift_line}\n\n"
        f"Персонал (расчёт):\n{details}\n\n"
        f"ИТОГО (ориентир): {total} RUB\n"
        f"(оценка за 1 день по графику; итог по проекту — у менеджера)\n\n"
        f"ФИО: {data.get('contact_name', '—')}\n"
        f"Компания: {co}\n"
        f"ИНН: {inn}\n"
        f"Телефон: {data.get('contact_phone', '—')}\n"
        f"Email: {data.get('contact_email', '—')}\n"
        f"Звонок: {data.get('call_time', '—')}\n\n"
        f"---\n{COMPANY_NAME}\nСайт: {WEBSITE_URL}\n"
    )


def _format_question_plain(q: str, qid: int, who: str) -> str:
    return (
        f"Новый вопрос #{qid}\n"
        f"================================\n\n"
        f"От: {who}\n\n"
        f"Вопрос:\n{q}\n\n"
        f"---\n{COMPANY_NAME}\nСайт: {WEBSITE_URL}\n"
    )


def _format_join_plain(data: dict[str, Any], rid: int, who: str) -> str:
    selfie = (data.get("selfie_ref") or "").strip() or "—"
    return (
        f"Новая заявка в команду #{rid}\n"
        f"================================\n\n"
        f"От: {who}\n\n"
        f"ФИО: {data.get('full_name', '—')}\n"
        f"Телефон: {data.get('phone', '—')}\n"
        f"Должность: {data.get('position', '—')}\n"
        f"Город: {data.get('city', '—')}\n"
        f"Метро: {data.get('metro', '—')}\n"
        f"Стаж: {data.get('experience_years', '—')}\n"
        f"Опыт: {data.get('experience_desc', '—')}\n"
        f"Навыки: {(data.get('skills') or '').strip() or '—'}\n"
        f"Селфи (ссылка/токен): {selfie}\n\n"
        f"---\n{COMPANY_NAME}\nСайт: {WEBSITE_URL}\n"
    )


async def _notify_plain(subject: str, plain: str) -> None:
    try:
        await notify_agency_admins(subject, plain)
    except Exception:
        logger.exception("notify_agency_admins failed")


def _order_preview_text(data: dict[str, Any]) -> str:
    staff = merged_staff_for_pricing(data)
    parsed = parse_shift_interval(data.get("shift_time", ""))
    details, total, meta = calculate_order_cost(staff, order_hourly_rates(), parsed)
    shift_human = data.get("shift_time") or "—"
    if meta.get("ok") and meta.get("shift_desc"):
        shift_human = f"{shift_human}\n_{meta['shift_desc']}_"
    co = (data.get("company_name") or "").strip() or "—"
    inn = (data.get("company_inn") or "").strip() or "—"
    return (
        f"*Проверьте данные*\n\n"
        f"*Клиент*\n"
        f"• ФИО: {data.get('contact_name')}\n"
        f"• Компания: {co}\n"
        f"• ИНН: {inn}\n"
        f"• Телефон: {data.get('contact_phone')}\n"
        f"• Email: {data.get('contact_email')}\n"
        f"• Звонок: {data.get('call_time')}\n\n"
        f"*Мероприятие*\n"
        f"• Тип: {data.get('event_type')}\n"
        f"• Город: {data.get('city')}\n"
        f"• Дата / период: {data.get('event_date')}\n"
        f"• Время смены: {shift_human}\n\n"
        f"*Персонал*\n{details or '—'}\n\n"
        f"_Сумма ориентировочная: один день с указанным графиком смены. "
        f"Итоговую стоимость проекта уточняйте у менеджера._\n\n"
        f"*ИТОГО (ориентир): {total:,} RUB*".replace(",", " ")
    )


def _supervisor_offer_text(total: int, rec: int) -> str:
    if total < 5:
        return (
            "*Супервайзер / тимлидер*\n\n"
            "При команде из нескольких человек на площадке мы рекомендуем "
            "супервайзера/тимлидера — координация состава и связь с заказчиком.\n\n"
            "Ориентировочно *900* ₽/ч в дневное окно 10:00–22:00; ночные часы смены — "
            "*+15%* к часу (как у остальных ролей в расчёте).\n\n"
            "Можно включить *1* супервайдера в предварительную оценку или оставить только исполнителей — "
            "итоговую схему уточнит менеджер."
        )
    return (
        "*Супервайзер / тимлидер*\n\n"
        f"При *{total}* сотрудниках обычно нужен *{rec}* супервайдер(ов) — "
        "ориентир *около одного на каждые 5* человек.\n\n"
        "Ориентировочно *900* ₽/ч в дневное окно 10:00–22:00; ночные часы смены — "
        "*+15%* к часу (как у остальных ролей).\n\n"
        "Включите супервайзеров в предварительный расчёт или оставьте только исполнителей — "
        "точный состав уточнит менеджер."
    )


async def process_callback(
    max_uid: int, payload: str, sender: dict[str, Any] | None
) -> dict[str, Any] | None:
    who = _sender_label(sender)
    s = SESSIONS.get(max_uid)
    if not s:
        return None
    flow = s.get("flow")
    step = s.get("step")
    data = s.setdefault("data", {})

    if flow == "order" and step == "staff_pick" and payload.startswith("o_"):
        try:
            idx = int(payload[2:])
        except ValueError:
            return None
        if idx < 0 or idx >= len(CLIENT_POSITIONS):
            return None
        pos = CLIENT_POSITIONS[idx]
        temp = s.setdefault("temp_staff", {})
        temp[pos] = int(temp.get(pos, 0)) + 1
        return {
            "text": (
                "Выберите категории персонала и количество (нажимайте для увеличения).\n\n"
                "_После выбора нажмите «Готово»._"
            ),
            "format": "markdown",
            "attachments": visit_card.order_staff_keyboard(temp),
        }

    if flow == "order" and step == "staff_pick" and payload == "staff_done":
        temp = s.get("temp_staff") or {}
        if not any(int(v) > 0 for v in temp.values()):
            return {
                "text": "Выберите хотя бы одну позицию кнопками выше, затем «Готово».",
                "format": "markdown",
                "attachments": visit_card.order_staff_keyboard(temp),
            }
        data["staff_counts"] = {k: int(v) for k, v in temp.items() if int(v) > 0}
        s.pop("temp_staff", None)
        total = total_staff_in_shift(data["staff_counts"])
        data["supervisor_count"] = 0
        if total < 2:
            s["step"] = "contact_phone"
            return {
                "text": (
                    "Укажите контактный телефон.\n\n"
                    "_Образец:_ `+79001234567`"
                ),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        rec = recommended_supervisor_count(total)
        data["supervisor_recommend"] = rec
        s["step"] = "supervisor_offer"
        return {
            "text": _supervisor_offer_text(total, rec),
            "format": "markdown",
            "attachments": visit_card.supervisor_offer_keyboard(),
        }

    if flow == "order" and step == "supervisor_offer" and payload == "sv_add":
        rec = int(data.get("supervisor_recommend") or 1)
        if rec < 1:
            rec = 1
        data["supervisor_count"] = rec
        sv_word = "супервайдер" if rec == 1 else "супервайзеров"
        s["step"] = "contact_phone"
        return {
            "text": f"В предварительный расчёт добавлено: *{rec}* {sv_word}.\n\nУкажите телефон.\n\n_Образец:_ `+79001234567`",
            "format": "markdown",
            "attachments": visit_card.back_to_main_keyboard(),
        }

    if flow == "order" and step == "supervisor_offer" and payload == "sv_skip":
        data["supervisor_count"] = 0
        s["step"] = "contact_phone"
        return {
            "text": (
                "Супервайзер в расчёт не включён — при необходимости менеджер предложит варианты.\n\n"
                "Укажите контактный телефон.\n\n"
                "_Образец:_ `+79001234567`"
            ),
            "format": "markdown",
            "attachments": visit_card.back_to_main_keyboard(),
        }

    if flow == "order" and step == "confirm" and payload == "order_send":
        oid = _new_id()
        to_save = dict(data)
        sc = int(to_save.get("supervisor_count") or 0)
        if sc > 0:
            scounts = dict(to_save.get("staff_counts") or {})
            scounts[SUPERVISOR_TM_LEAD] = sc
            to_save["staff_counts"] = scounts
        staff = merged_staff_for_pricing(to_save)
        parsed = parse_shift_interval(to_save.get("shift_time", ""))
        _, total, meta = calculate_order_cost(staff, order_hourly_rates(), parsed)
        to_save["total_cost"] = total
        to_save["cost_meta"] = meta
        plain = _format_order_plain(to_save, oid, who)
        await _notify_plain(f"Новая заявка на расчёт #{oid}", plain)
        funnel_touch_complete(max_uid)
        clear_session(max_uid)
        return {
            "text": (
                f"*Заявка #{oid} принята.*\n\n"
                "Спасибо! Менеджер свяжется с вами в ближайшее время."
            ),
            "format": "markdown",
            "attachments": visit_card.main_menu_keyboard(),
        }

    if flow == "order" and step == "confirm" and payload == "order_edit":
        clear_session(max_uid)
        return start_order(max_uid)

    if flow == "join" and step == "experience_years" and payload.startswith("exp_"):
        try:
            ei = int(payload.replace("exp_", "", 1))
        except ValueError:
            return None
        if ei < 0 or ei >= len(EXPERIENCE_OPTIONS):
            return None
        data["experience_years"] = EXPERIENCE_OPTIONS[ei]
        s["step"] = "experience_desc"
        return {
            "text": (
                "Кратко опишите опыт: где работали, какие задачи.\n\n"
                "_Образец:_ `Промо в торговых центрах 2 года, выкладка, коммуникация с гостями`"
            ),
            "format": "markdown",
            "attachments": visit_card.back_to_main_keyboard(),
        }

    if flow == "join" and step == "review_submit" and payload == "submit_join":
        rid = _new_id()
        plain = _format_join_plain(data, rid, who)
        await _notify_plain(f"Новая заявка в команду #{rid}", plain)
        funnel_touch_complete(max_uid)
        clear_session(max_uid)
        return {
            "text": (
                f"*Заявка #{rid} принята.*\n\n"
                "Спасибо за интерес к PROMOSTAFF AGENCY!"
            ),
            "format": "markdown",
            "attachments": visit_card.main_menu_keyboard(),
        }

    if flow == "join" and step == "position_pick":
        if payload == "jpos_other":
            s["step"] = "position_text"
            return {
                "text": "Введите желаемую должность одной строкой:",
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if payload.startswith("jpos_"):
            try:
                idx = int(payload[5:])
            except ValueError:
                return None
            if idx < 0 or idx >= len(APPLICANT_POSITIONS[:12]):
                return None
            data["position"] = APPLICANT_POSITIONS[idx]
            s["step"] = "full_name"
            return {
                "text": (
                    "Укажите ваше полное ФИО.\n\n"
                    "_Образец:_ `Иванов Иван Иванович`"
                ),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }

    return None


async def process_text(
    max_uid: int,
    text: str,
    sender: dict[str, Any] | None,
    message_body: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    s = SESSIONS.get(max_uid)
    if not s:
        return None
    who = _sender_label(sender)
    flow = s.get("flow")
    step = s.get("step")
    data = s.setdefault("data", {})

    if flow == "question" and step == "text":
        qid = _new_id()
        plain = _format_question_plain(text, qid, who)
        await _notify_plain(f"Новый вопрос #{qid}", plain)
        clear_session(max_uid)
        return {
            "text": "*Сообщение отправлено.* Спасибо!",
            "format": "markdown",
            "attachments": visit_card.main_menu_keyboard(),
        }

    if flow == "order":
        if step == "event_type":
            data["event_type"] = text.strip()
            s["step"] = "city"
            return {
                "text": "Укажите город проведения мероприятия.\n\n_Образец:_ `Москва`",
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "city":
            data["city"] = text.strip()
            s["step"] = "event_date"
            return {
                "text": (
                    "Укажите дату мероприятия или период (можно несколько дней).\n\n"
                    "_Образец:_ `15.06.2026` или `12–14 июня 2026`"
                ),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "event_date":
            data["event_date"] = text.strip()
            s["step"] = "shift_time"
            return {
                "text": "*Время смены*\n\n" + SHIFT_STEP_TEXT,
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "shift_time":
            raw = text.strip()
            if not parse_shift_interval(raw):
                return {
                    "text": (
                        "Не удалось разобрать время. Укажите одну смену как `чч:мм-чч:мм`, "
                        "например `10:00-22:00`."
                    ),
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["shift_time"] = raw
            s["step"] = "staff_pick"
            s["temp_staff"] = {}
            return {
                "text": (
                    "Выберите категории персонала и количество (нажимайте для увеличения).\n\n"
                    "_После выбора нажмите «Готово»._"
                ),
                "format": "markdown",
                "attachments": visit_card.order_staff_keyboard({}),
            }
        if step == "contact_phone":
            v = validate_phone(text)
            if not v:
                return {
                    "text": "Неверный формат. Пример: `+79001234567`",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["contact_phone"] = v
            s["step"] = "contact_name"
            return {
                "text": "Введите полное ФИО.\n\n_Образец:_ `Иванов Иван Иванович`",
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "contact_name":
            if not validate_full_name(text):
                return {
                    "text": "Введите полное ФИО (минимум 2 слова). Пример: Иванов Иван Иванович",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["contact_name"] = text.strip()
            s["step"] = "contact_email"
            return {
                "text": "Введите email для связи.\n\n_Образец:_ `client@company.ru`",
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "contact_email":
            if not validate_email(text.strip()):
                return {
                    "text": "Некорректный email. Пример: client@company.ru",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["contact_email"] = text.strip()
            s["step"] = "company_name"
            return {
                "text": "Укажите название компании (или `—` если нет).\n\n_Образец:_ `ООО «Ромашка»`",
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "company_name":
            company = text.strip()
            if company == "—":
                company = ""
            data["company_name"] = company
            s["step"] = "company_inn"
            return {
                "text": (
                    "Укажите ИНН компании (10 или 12 цифр).\n\n"
                    "_Образец:_ `7707083893`\n"
                    "Если ИНН нет — отправьте `0`."
                ),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "company_inn":
            raw = text.strip()
            if raw == "0":
                data["company_inn"] = ""
            else:
                if not validate_inn(raw):
                    return {
                        "text": "ИНН должен содержать 10 или 12 цифр. Пример: 7707083893",
                        "format": "markdown",
                        "attachments": visit_card.back_to_main_keyboard(),
                    }
                data["company_inn"] = re.sub(r"\D", "", raw)
            s["step"] = "call_time"
            return {
                "text": "Когда удобно принять звонок менеджера?\n\n_Образец:_ `будни 10:00–18:00`",
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "call_time":
            data["call_time"] = text.strip()
            s["step"] = "confirm"
            staff = merged_staff_for_pricing(data)
            parsed = parse_shift_interval(data.get("shift_time", ""))
            _, total, meta = calculate_order_cost(staff, order_hourly_rates(), parsed)
            data["total_cost"] = total
            data["cost_meta"] = meta
            return {
                "text": _order_preview_text(data),
                "format": "markdown",
                "attachments": visit_card.order_confirm_keyboard(),
            }
        if step == "confirm":
            return {
                "text": "Используйте кнопки под сообщением: отправить заявку или изменить данные.",
                "format": "markdown",
                "attachments": visit_card.order_confirm_keyboard(),
            }
        if step in ("staff_pick", "supervisor_offer"):
            return {
                "text": "На этом шаге выберите варианты кнопками выше.",
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }

    if flow == "join":
        if step == "position_text":
            pos = text.strip()
            if len(pos) < 2:
                return {
                    "text": "Слишком коротко. Укажите должность текстом.",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["position"] = pos
            s["step"] = "full_name"
            return {
                "text": (
                    "Укажите ваше полное ФИО.\n\n"
                    "_Образец:_ `Иванов Иван Иванович`"
                ),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "full_name":
            if not validate_full_name(text):
                return {
                    "text": "ФИО: минимум 2 слова. Пример: Иванов Иван Иванович",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["full_name"] = text.strip()
            s["step"] = "phone"
            return {
                "text": "Укажите телефон.\n\n_Образец:_ `+79001234567`",
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "phone":
            v = validate_phone(text)
            if not v:
                return {
                    "text": "Пример: +79001234567",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["phone"] = v
            s["step"] = "city"
            return {
                "text": "Укажите город проживания.\n\n_Образец:_ `Москва`",
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "city":
            data["city"] = text.strip()
            s["step"] = "metro"
            return {
                "text": (
                    "Ближайшая станция метро (если в городе нет метро — отправьте `0`).\n\n"
                    "_Образец:_ `Тверская` или `0`"
                ),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "metro":
            if not validate_metro(text):
                return {
                    "text": "Укажите название станции или `0`, если метро нет.",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["metro"] = text.strip()
            s["step"] = "experience_years"
            return {
                "text": "Выберите стаж кнопкой ниже.",
                "format": "markdown",
                "attachments": visit_card.experience_keyboard(),
            }
        if step == "experience_desc":
            if len(text.strip()) < 5:
                return {
                    "text": "Слишком коротко. Например: «Промо в ТЦ, выкладка, общение с гостями».",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["experience_desc"] = text.strip()
            s["step"] = "skills"
            return {
                "text": (
                    "Дополнительные навыки (языки, ПО, права, медкнижка и т.д.).\n\n"
                    "_Образец:_ `Английский B1, права кат. B`\n"
                    "Если нечего добавить — отправьте `—`."
                ),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "skills":
            skills = text.strip()
            if skills == "—":
                skills = ""
            data["skills"] = skills
            s["step"] = "selfie"
            return {
                "text": (
                    "Пришлите *селфи* для подтверждения анкеты (фото вложением).\n\n"
                    "Лицо должно быть хорошо видно."
                ),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "selfie":
            ref = _image_ref_from_body(message_body)
            if not ref:
                return {
                    "text": "Нужно отправить фото (селфи) вложением, не только текст.",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["selfie_ref"] = ref
            s["step"] = "review_submit"
            preview = (
                "*Проверьте анкету*\n\n"
                f"ФИО: {data.get('full_name')}\n"
                f"Телефон: {data.get('phone')}\n"
                f"Должность: {data.get('position')}\n"
                f"Город: {data.get('city')}\n"
                f"Метро: {data.get('metro')}\n"
                f"Стаж: {data.get('experience_years')}\n"
                f"Опыт: {data.get('experience_desc')}\n"
                f"Навыки: {data.get('skills') or '—'}\n"
                "Селфи: получено\n\n"
                "Нажмите *«Отправить анкету»*."
            )
            return {
                "text": preview,
                "format": "markdown",
                "attachments": visit_card.submit_join_keyboard(),
            }
        if step == "review_submit":
            return {
                "text": "Нажмите кнопку «Отправить анкету» ниже.",
                "format": "markdown",
                "attachments": visit_card.submit_join_keyboard(),
            }
        if step == "experience_years":
            return {
                "text": "Выберите стаж кнопкой.",
                "format": "markdown",
                "attachments": visit_card.experience_keyboard(),
            }

    return None
