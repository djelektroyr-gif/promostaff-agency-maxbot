"""
Сценарии FSM: заказ расчёта (как Telegram-визитка), вопрос менеджеру, анкета в команду.
Состояние в памяти. Уведомления — notify.notify_agency_admins.

Визитка: где уместно — явные офферы (супервайзер при 2+ в смене, менеджер для сметы/периода)
и короткий `notification` в ответах на callback — нативная обратная связь MAX.
"""
from __future__ import annotations

import logging
import random
import re
import time
import json
from typing import Any

from config import (
    APPLICANT_POSITIONS,
    CLIENT_POSITIONS,
    COMPANY_NAME,
    EXPERIENCE_OPTIONS,
    SUPERVISOR_TM_LEAD,
    PRIVACY_POLICY_URL,
    WEBSITE_URL,
    order_hourly_rates,
)

import visit_card
from funnel_store import funnel_touch_complete
from funnel_db import (
    is_max_visit_client_verified,
    save_max_visit_client_verified,
    save_visit_join,
    save_visit_order,
    save_visit_question,
)
from notify import notify_agency_admins
from shift_pricing import calculate_order_cost, parse_shift_interval

logger = logging.getLogger(__name__)

SESSIONS: dict[int, dict[str, Any]] = {}


SHIFT_STEP_TEXT = (
    "Время работы персонала (одна смена в типичный день)\n\n"
    "Укажите интервал в формате *чч:мм - чч:мм* по времени площадки.\n\n"
    "*Примеры:* `10:00-22:00` (дневная), `22:00-06:00` (через полночь), `08:00-18:00`.\n\n"
    "Дневной тариф: часы с *10:00 до 22:00*. Остальные часы смены — ночные "
    "(*+15% к часу*).\n"
    "Если в смене есть хотя бы один ночной час — минимум *8* оплачиваемых часов на человека; "
    "если смена только дневная — минимум *6* часов.\n\n"
    "Дату или период вы уже указали выше — здесь только время смены.\n\n"
    "💡 *Несколько дней подряд?* Оценка в боте — за *один* типичный день с этим графиком; "
    "сводку по всему периоду и КП — с менеджером (раздел «Связаться с менеджером»).\n\n"
    "_Образец:_ `10:00-22:00`\n\n"
    "👇"
)


def _new_id() -> int:
    return int(time.time()) % 900_000_000 + random.randint(0, 99_999)


def _consent_gate_text(scope: str) -> str:
    return (
        f"*Согласие на обработку персональных данных ({scope})*\n\n"
        "Перед продолжением ознакомьтесь с Политикой и подтвердите согласие на обработку "
        "персональных данных в соответствии с 152-ФЗ.\n\n"
        "Оператор данных: ООО «ПРОМОСТАФФ» (ИНН 5003172663, КПП 500301001, "
        "ОГРН 1265000003025). Мы используем только необходимые данные для связи, "
        "обработки заявки и предоставления сервиса.\n\n"
        "Нажимая «Согласен с обработкой данных», вы подтверждаете ознакомление с Политикой "
        "и даёте согласие на обработку персональных данных для указанной цели.\n\n"
        "👇"
    )


def _consent_pd_tail() -> str:
    return (
        "Перед продолжением ознакомьтесь с Политикой и подтвердите согласие на обработку "
        "персональных данных в соответствии с 152-ФЗ.\n\n"
        "Оператор данных: ООО «ПРОМОСТАФФ» (ИНН 5003172663, КПП 500301001, "
        "ОГРН 1265000003025)."
    )


def _client_visit_entry_text() -> str:
    return (
        "*Регистрация заказчика (юрлицо)*\n\n"
        "Перед расчётом нужно указать реквизиты организации и пройти подтверждение данных.\n\n"
        + _consent_pd_tail()
        + "\n\n👇"
    )


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


def validate_radius_km(text: str) -> int | None:
    t = re.sub(r"[^\d]", "", (text or "").strip())
    if not t:
        return None
    v = int(t)
    if v < 0 or v > 200:
        return None
    return v


def _experience_tag(value: str) -> str:
    v = (value or "").strip().lower()
    if "менее" in v:
        return "junior"
    if "1-3" in v or "1–3" in v:
        return "middle"
    if "более" in v:
        return "senior"
    return "unknown"


def _build_specialization_tags(data: dict[str, Any]) -> str:
    tags: list[str] = []
    pos = (data.get("position") or "").strip()
    track = (data.get("profile_track") or "").strip()
    shift = (data.get("preferred_shift") or "").strip()
    if pos:
        tags.append(pos)
    if track:
        tags.append(track)
    if shift:
        tags.append(f"смены:{shift}")
    uniq: list[str] = []
    for t in tags:
        if t not in uniq:
            uniq.append(t)
    return ", ".join(uniq)


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


def _media_ref_from_body(message_body: dict[str, Any] | None) -> str | None:
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
        if t not in ("image", "photo", "picture", "video", "file"):
            continue
        p = a.get("payload")
        if isinstance(p, dict):
            for key in ("url", "photo_url", "video_url", "small_url", "medium_url", "token"):
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


def start_order(max_uid: int, *, announce_order_consent: bool = True) -> dict[str, Any]:
    clear_session(max_uid)
    if not is_max_visit_client_verified(max_uid):
        SESSIONS[max_uid] = {"flow": "client_visit", "step": "consent", "data": {}}
        return {
            "notification": "Сначала регистрация заказчика.",
            "text": _client_visit_entry_text(),
            "format": "markdown",
            "attachments": visit_card.consent_gate_keyboard("client_visit"),
        }
    SESSIONS[max_uid] = {"flow": "order", "step": "consent", "data": {}}
    msg: dict[str, Any] = {
        "text": _consent_gate_text("заказ расчёта"),
        "format": "markdown",
        "attachments": visit_card.consent_gate_keyboard("order"),
    }
    if announce_order_consent:
        msg["notification"] = "Сначала подтвердите согласие на обработку данных."
    return msg


def start_fill_anketa(max_uid: int) -> dict[str, Any]:
    """Запуск полной анкеты исполнителя прямо в MAX-визитке."""
    return start_join(max_uid)


def start_question(max_uid: int) -> dict[str, Any]:
    clear_session(max_uid)
    SESSIONS[max_uid] = {"flow": "question", "step": "consent", "data": {}}
    return {
        "text": _consent_gate_text("вопрос менеджеру"),
        "format": "markdown",
        "attachments": visit_card.consent_gate_keyboard("question"),
    }


def start_join(max_uid: int) -> dict[str, Any]:
    clear_session(max_uid)
    SESSIONS[max_uid] = {
        "flow": "join",
        "step": "consent",
        "data": {"profile_track": "", "join_entry": "profile"},
    }
    return {
        "text": _consent_gate_text("отклик в команду"),
        "format": "markdown",
        "attachments": visit_card.consent_gate_keyboard("join"),
    }


def join_from_vacancy(max_uid: int, payload: str) -> dict[str, Any] | None:
    title = VAC_FROM_KEY.get(payload)
    if not title:
        return None
    clear_session(max_uid)
    SESSIONS[max_uid] = {
        "flow": "join",
        "step": "consent",
        "data": {"position": title, "join_entry": "vacancy"},
    }
    return {
        "text": _consent_gate_text("отклик в команду"),
        "format": "markdown",
        "attachments": visit_card.consent_gate_keyboard("join"),
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
    track = (data.get("profile_track") or "").strip() or "—"
    portfolio = data.get("portfolio_refs") or []
    p_count = len(portfolio) if isinstance(portfolio, list) else 0
    priority = "Да" if data.get("priority_pool") else "Нет"
    spec_tags = (data.get("specialization_tags") or "").strip() or "—"
    exp_tag = (data.get("experience_tag") or "").strip() or "—"
    return (
        f"Новая заявка в команду #{rid}\n"
        f"================================\n\n"
        f"От: {who}\n\n"
        f"ФИО: {data.get('full_name', '—')}\n"
        f"Телефон: {data.get('phone', '—')}\n"
        f"Трек: {track}\n"
        f"Должность: {data.get('position', '—')}\n"
        f"Город: {data.get('city', '—')}\n"
        f"Метро: {data.get('metro', '—')}\n"
        f"Предпочтительные смены: {data.get('preferred_shift', '—')}\n"
        f"Радиус выезда: {data.get('travel_radius_km', '—')} км\n"
        f"Документы: {data.get('docs_ready', '—')}\n"
        f"Стаж: {data.get('experience_years', '—')}\n"
        f"Опыт: {data.get('experience_desc', '—')}\n"
        f"Навыки: {(data.get('skills') or '').strip() or '—'}\n"
        f"Портфолио: {p_count} файл(ов)\n"
        f"Приоритетный пул: {priority}\n"
        f"Теги специализации: {spec_tags}\n"
        f"Тег опыта: {exp_tag}\n"
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
        "_Сумма ориентировочная: один день с указанным графиком смены. Итог по проекту и договорённостям — у менеджера._\n"
        f"*ИТОГО (ориентир): {total:,} RUB*".replace(",", " ")
        + "\n\n👇"
    )


def _supervisor_offer_text(total: int, rec: int) -> str:
    if total < 5:
        return (
            "*Супервайзер / тимлидер*\n\n"
            "При команде из нескольких человек на площадке мы рекомендуем "
            "супервайзера/тимлидера — координация состава и связь с заказчиком.\n\n"
            "Ориентировочно *900* ₽/ч в дневное окно 10:00–22:00; ночные часы смены — "
            "*+15%* к часу (как у остальных ролей в расчёте).\n\n"
            "Можно включить *1* супервайзера в предварительную оценку или оставить только исполнителей — "
            "итоговую схему уточнит менеджер.\n\n"
            "👇"
        )
    return (
        "*Супервайзер / тимлидер*\n\n"
        f"При *{total}* сотрудниках обычно нужен *{rec}* супервайзер(ов) — "
        "ориентир *около одного на каждые 5* человек.\n\n"
        "Ориентировочно *900* ₽/ч в дневное окно 10:00–22:00; ночные часы смены — "
        "*+15%* к часу (как у остальных ролей).\n\n"
        "Включите супервайзеров в предварительный расчёт или оставьте только исполнителей — "
        "точный состав уточнит менеджер.\n\n"
        "👇"
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

    if flow == "client_visit" and step == "consent" and payload == "consent_client_visit_accept":
        s["step"] = "company_name"
        return {
            "notification": "Согласие принято ✅",
            "text": (
                "🏢 *Регистрация заказчика*\n\n"
                "Шаг 1/6: введите *полное* юридическое название организации (как в учредительных документах):"
            ),
            "format": "markdown",
            "attachments": visit_card.back_to_main_keyboard(),
        }

    if flow == "client_visit" and step == "confirm" and payload == "confirm_client_visit_yes":
        username = (sender or {}).get("username") if isinstance(sender, dict) else ""
        try:
            save_max_visit_client_verified(max_uid, str(username or ""), data)
        except Exception:
            logger.exception("save_max_visit_client_verified")
        SESSIONS[max_uid] = {"flow": "order", "step": "event_type", "data": {"order_consent_accepted": True}}
        return {
            "notification": "Отлично!",
            "text": (
                "*Заказ расчёта стоимости*\n\n"
                "Выберите быстрый сценарий или введите тип проекта вручную.\n\n"
                "Быстрый сценарий ускорит заполнение формы.\n\n"
                "👇"
            ),
            "format": "markdown",
            "attachments": visit_card.order_quickstart_keyboard(),
        }

    if flow == "client_visit" and step == "confirm" and payload == "confirm_client_visit_edit":
        data.clear()
        s["step"] = "consent"
        return {
            "text": _client_visit_entry_text(),
            "format": "markdown",
            "attachments": visit_card.consent_gate_keyboard("client_visit"),
        }

    if flow == "order" and step == "consent" and payload == "consent_order_accept":
        data["order_consent_accepted"] = True
        s["step"] = "event_type"
        return {
            "notification": "Согласие принято ✅",
            "text": (
                "*Заказ расчёта стоимости*\n\n"
                "Выберите быстрый сценарий или введите тип проекта вручную.\n\n"
                "Быстрый сценарий ускорит заполнение формы.\n\n"
                "👇"
            ),
            "format": "markdown",
            "attachments": visit_card.order_quickstart_keyboard(),
        }

    if flow == "question" and step == "consent" and payload == "consent_question_accept":
        data["question_consent_accepted"] = True
        s["step"] = "text"
        return {
            "notification": "Согласие принято ✅",
            "text": (
                "*Сообщение менеджеру*\n\n"
                "Напишите вопрос одним сообщением — мы ответим в рабочее время.\n\n"
                "👇"
            ),
            "format": "markdown",
            "attachments": visit_card.back_to_main_keyboard(),
        }

    if flow == "join" and step == "consent" and payload == "consent_join_accept":
        data["join_consent_accepted"] = True
        if data.get("join_entry") == "vacancy" and data.get("position"):
            s["step"] = "full_name"
            return {
                "notification": "Согласие принято ✅",
                "text": (
                    f"Должность: *{data.get('position')}*\n\n"
                    "Введите полное ФИО.\n\n"
                    "_Образец:_ `Иванов Иван Иванович`\n\n"
                    "👇"
                ),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        s["step"] = "profile_pick"
        return {
            "notification": "Согласие принято ✅",
            "text": "Выберите ваш формат занятости, чтобы мы быстрее подобрали подходящую роль:\n\n👇",
            "format": "markdown",
            "attachments": visit_card.join_profile_keyboard(),
        }

    if flow == "order" and step == "staff_pick" and payload.startswith("pos_"):
        pos = payload.replace("pos_", "", 1)
        if pos not in CLIENT_POSITIONS:
            return None
        temp = s.setdefault("temp_staff", {})
        temp[pos] = int(temp.get(pos, 0)) + 1
        n = temp[pos]
        return {
            "notification": f"{pos}: {n} чел.",
            "text": (
                "Выберите категории персонала и количество (нажимайте для увеличения).\n\n"
                "_После выбора нажмите «Готово»._\n\n"
                "👇"
            ),
            "format": "markdown",
            "attachments": visit_card.order_staff_keyboard(temp),
        }

    if flow == "order" and step == "event_type" and payload.startswith("quick_"):
        presets = {
            "quick_urgent": "Срочный проект (24 часа), оперативный запуск",
            "quick_expo": "Выставка, стенд и поток гостей",
            "quick_corp": "Корпоративное мероприятие",
        }
        if payload == "quick_custom":
            return {
                "notification": "Введите свой тип проекта",
                "text": (
                    "Укажите тип мероприятия (выставка, концерт, корпоратив и т.д.).\n\n"
                    "_Образец:_ `Корпоратив, 200 гостей`\n\n"
                    "👇"
                ),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        preset = presets.get(payload)
        if not preset:
            return None
        data["event_type"] = preset
        s["step"] = "city"
        return {
            "notification": "Сценарий применён ✅",
            "text": "Укажите город проведения мероприятия.\n\n_Образец:_ `Москва`\n\n👇",
            "format": "markdown",
            "attachments": visit_card.back_to_main_keyboard(),
        }

    if flow == "order" and step == "staff_pick" and payload == "positions_done":
        temp = s.get("temp_staff") or {}
        if not any(int(v) > 0 for v in temp.values()):
            return {
                "notification": "Выберите хотя бы одну позицию.",
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
                "notification": "📞 Дальше — контакт для связи.",
                "text": (
                    "Отправьте контакт телефона кнопкой ниже или введите вручную.\n\n"
                    "_Образец:_ `+79001234567`\n\n"
                    "👇"
                ),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        rec = recommended_supervisor_count(total)
        data["supervisor_recommend"] = rec
        s["step"] = "supervisor_offer"
        return {
            "notification": "👔 Рекомендуем супервайзера/тимлидера — см. следующее сообщение.",
            "text": _supervisor_offer_text(total, rec),
            "format": "markdown",
            "attachments": visit_card.supervisor_offer_keyboard(),
        }

    if flow == "order" and step == "supervisor_offer" and payload == "sv_add":
        rec = int(data.get("supervisor_recommend") or 1)
        if rec < 1:
            rec = 1
        data["supervisor_count"] = rec
        sv_word = "супервайзер" if rec == 1 else "супервайзеров"
        s["step"] = "contact_phone"
        return {
            "notification": "✅ Супервайзер в оценке (900 ₽/ч днём, ночь +15%). Дальше — телефон.",
            "text": (
                f"В предварительный расчёт добавлено: *{rec}* {sv_word}.\n\n"
                "Отправьте контакт телефона кнопкой ниже или введите вручную.\n\n"
                "_Образец:_ `+79001234567`\n\n"
                "👇"
            ),
            "format": "markdown",
            "attachments": visit_card.back_to_main_keyboard(),
        }

    if flow == "order" and step == "supervisor_offer" and payload == "sv_skip":
        data["supervisor_count"] = 0
        s["step"] = "contact_phone"
        return {
            "notification": "Ок. По супервайзеру и составу можно обсудить с менеджером после заявки.",
            "text": (
                "Супервайзер в расчёт не включён — при необходимости менеджер предложит варианты.\n\n"
                "Отправьте контакт телефона кнопкой ниже или введите вручную.\n\n"
                "_Образец:_ `+79001234567`\n\n"
                "👇"
            ),
            "format": "markdown",
            "attachments": visit_card.back_to_main_keyboard(),
        }

    if flow == "order" and step == "confirm" and payload == "confirm_order":
        if not data.get("order_consent_accepted"):
            return {
                "notification": "Подтвердите согласие на обработку персональных данных перед отправкой заявки.",
                "text": (
                    "Перед отправкой заявки подтвердите согласие кнопкой ниже.\n\n"
                    f"Политика: {PRIVACY_POLICY_URL}\n\n"
                    "👇"
                ),
                "format": "markdown",
                "attachments": visit_card.order_confirm_keyboard(),
            }
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
        username = (sender or {}).get("username") if isinstance(sender, dict) else ""
        try:
            save_visit_order(max_uid, str(username or ""), json.dumps(to_save, ensure_ascii=False))
        except Exception:
            logger.exception("save_visit_order")
        funnel_touch_complete(max_uid)
        clear_session(max_uid)
        return {
            "notification": "✅ Заявка у команды. Менеджер свяжется для уточнения деталей и точной сметы.",
            "text": (
                f"*Заявка #{oid} принята.*\n\n"
                "Спасибо! Менеджер свяжется с вами в ближайшее время.\n\n"
                "👇"
            ),
            "format": "markdown",
            "attachments": visit_card.main_menu_keyboard(),
        }

    if flow == "order" and step == "confirm" and payload == "edit_order":
        clear_session(max_uid)
        msg = start_order(max_uid, announce_order_consent=False)
        msg["notification"] = "Заполняем заявку заново…"
        return msg

    if flow == "join" and step == "experience_years" and payload.startswith("exp_"):
        exp = payload.replace("exp_", "", 1)
        data["experience_years"] = exp
        s["step"] = "experience_desc"
        return {
            "notification": f"Стаж: {exp}",
            "text": (
                "Кратко опишите опыт: где работали, какие задачи.\n\n"
                "_Образец:_ `Промо в торговых центрах 2 года, выкладка, коммуникация с гостями`\n\n"
                "👇"
            ),
            "format": "markdown",
            "attachments": visit_card.back_to_main_keyboard(),
        }

    if flow == "join" and step == "preferred_shift" and payload.startswith("shift_"):
        mapping = {
            "shift_day": "Дневные",
            "shift_night": "Ночные",
            "shift_both": "Оба варианта",
        }
        label = mapping.get(payload)
        if not label:
            return None
        data["preferred_shift"] = label
        s["step"] = "travel_radius"
        return {
            "notification": f"Смены: {label}",
            "text": "Укажите радиус выезда от вашего города в км.\n\n_Образец:_ `15`",
            "format": "markdown",
            "attachments": visit_card.back_to_main_keyboard(),
        }

    if flow == "join" and step == "docs_ready" and payload.startswith("docs_"):
        mapping = {
            "docs_med": "Медкнижка",
            "docs_self": "Самозанятость",
            "docs_ip": "ИП",
            "docs_later": "Оформлю при необходимости",
        }
        label = mapping.get(payload)
        if not label:
            return None
        data["docs_ready"] = label
        s["step"] = "experience_years"
        return {
            "notification": f"Документы: {label}",
            "text": "Выберите стаж кнопкой.\n\n👇",
            "format": "markdown",
            "attachments": visit_card.experience_keyboard(),
        }

    if flow == "join" and step == "portfolio" and payload == "portfolio_done":
        refs = list(data.get("portfolio_refs") or [])
        if not refs:
            return {
                "notification": "Нужно минимум 1 фото/видео.",
                "text": "Сначала отправьте минимум 1 файл портфолио.\n\n👇",
                "format": "markdown",
                "attachments": visit_card.join_portfolio_keyboard(),
            }
        s["step"] = "priority_pool"
        return {
            "notification": "Портфолио сохранено ✅",
            "text": (
                "Хотите попасть в приоритетный пул исполнителей?\n\n"
                "В приоритетном пуле чаще предлагаем проекты первыми.\n\n"
                "👇"
            ),
            "format": "markdown",
            "attachments": visit_card.join_priority_keyboard(),
        }

    if flow == "join" and step == "priority_pool" and payload in ("prio_yes", "prio_no"):
        data["priority_pool"] = payload == "prio_yes"
        data["specialization_tags"] = _build_specialization_tags(data)
        data["experience_tag"] = _experience_tag(str(data.get("experience_years") or ""))
        s["step"] = "review_submit"
        priority_text = "Да" if data.get("priority_pool") else "Нет"
        p_count = len(data.get("portfolio_refs") or [])
        preview = (
            "*Проверьте анкету*\n\n"
            f"ФИО: {data.get('full_name')}\n"
            f"Телефон: {data.get('phone')}\n"
            f"Трек: {data.get('profile_track') or '—'}\n"
            f"Должность: {data.get('position')}\n"
            f"Город: {data.get('city')}\n"
            f"Метро: {data.get('metro')}\n"
            f"Предпочтительные смены: {data.get('preferred_shift')}\n"
            f"Радиус выезда: {data.get('travel_radius_km')} км\n"
            f"Документы: {data.get('docs_ready')}\n"
            f"Стаж: {data.get('experience_years')}\n"
            f"Опыт: {data.get('experience_desc')}\n"
            f"Навыки: {data.get('skills') or '—'}\n"
            f"Портфолио: {p_count} файл(ов)\n"
            f"Приоритетный пул: {priority_text}\n"
            f"Теги специализации: {data.get('specialization_tags') or '—'}\n"
            f"Тег опыта: {data.get('experience_tag') or '—'}\n"
            "Селфи: получено\n\n"
            "Нажмите *«Отправить анкету»*.\n\n"
            "👇"
        )
        return {
            "notification": "Отметили ✅",
            "text": preview,
            "format": "markdown",
            "attachments": visit_card.submit_join_keyboard(),
        }

    if flow == "join" and step == "review_submit" and payload == "submit_join_anketa":
        rid = _new_id()
        plain = _format_join_plain(data, rid, who)
        await _notify_plain(f"Новая заявка в команду #{rid}", plain)
        username = (sender or {}).get("username") if isinstance(sender, dict) else ""
        try:
            save_visit_join(max_uid, str(username or ""), json.dumps(data, ensure_ascii=False))
        except Exception:
            logger.exception("save_visit_join")
        funnel_touch_complete(max_uid)
        clear_session(max_uid)
        return {
            "notification": "✅ Анкета у команды. Ответим после рассмотрения.",
            "text": (
                f"*Заявка #{rid} принята.*\n\n"
                f"Спасибо за интерес к {COMPANY_NAME}!\n\n"
                "👇"
            ),
            "format": "markdown",
            "attachments": visit_card.main_menu_keyboard(),
        }

    if flow == "join" and step == "position_pick":
        if payload == "jpos_other":
            s["step"] = "position_text"
            return {
                "notification": "Введите должность текстом.",
                "text": "Введите желаемую должность одной строкой:\n\n👇",
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
                "notification": f"Должность: {APPLICANT_POSITIONS[idx]}",
                "text": (
                    "Введите полное ФИО.\n\n"
                    "_Образец:_ `Иванов Иван Иванович`\n\n"
                    "👇"
                ),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }

    if flow == "join" and step == "profile_pick" and payload.startswith("jp_"):
        tracks = {
            "jp_exp": "С опытом в ивентах",
            "jp_beginner": "Начинающий",
            "jp_weekend": "Подработка по выходным",
            "jp_direct": "Без трека (прямой выбор роли)",
        }
        track = tracks.get(payload)
        if not track:
            return None
        data["profile_track"] = track
        s["step"] = "position_pick"
        return {
            "notification": "Отлично, идём дальше.",
            "text": "Выберите желаемую должность:\n\n👇",
            "format": "markdown",
            "attachments": visit_card.join_applicant_pick_keyboard(),
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

    if step == "consent":
        if flow == "client_visit":
            return {
                "text": "Нажмите кнопку согласия ниже или вернитесь в меню.\n\n👇",
                "format": "markdown",
                "attachments": visit_card.consent_gate_keyboard("client_visit"),
            }
        scope = {
            "order": "заказ расчёта",
            "join": "отклик в команду",
            "question": "вопрос менеджеру",
        }.get(str(flow), "форма")
        return {
            "text": _consent_gate_text(scope),
            "format": "markdown",
            "attachments": visit_card.consent_gate_keyboard(str(flow)),
        }

    if flow == "client_visit":
        if step == "company_name":
            t = text.strip()
            if len(t) < 2:
                return {
                    "text": "❌ Введите название организации (минимум 2 символа).",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["company_name"] = t
            s["step"] = "inn"
            return {
                "text": (
                    "Шаг 2/6: введите *ИНН* организации (10 цифр для юрлица или 12 для ИП) — сразу после названия, "
                    "чтобы мы могли сверить компанию."
                ),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "inn":
            raw = text.strip()
            if not validate_inn(raw):
                return {
                    "text": "❌ ИНН должен содержать 10 или 12 цифр.",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["inn"] = re.sub(r"\D", "", raw)
            s["step"] = "contact_name"
            return {
                "text": "Шаг 3/6: введите *полное ФИО* контактного лица (как в договоре):",
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "contact_name":
            if not validate_full_name(text):
                return {
                    "text": "❌ Введите полное ФИО (минимум 2 слова, кириллица или латиница).",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["contact_name"] = text.strip()
            s["step"] = "position_in_org"
            return {
                "text": "Шаг 4/6: укажите *вашу должность* в организации:",
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "position_in_org":
            t = text.strip()
            if len(t) < 2:
                return {
                    "text": "❌ Укажите должность (минимум 2 символа).",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["position_in_org"] = t
            s["step"] = "phone"
            return {
                "text": "Шаг 5/6: отправьте номер телефона кнопкой или введите вручную в формате +7…\n\n👇",
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "phone":
            v = validate_phone(text)
            if not v:
                return {
                    "text": "❌ Не удалось распознать номер. Введите +7XXXXXXXXXX или отправьте контакт кнопкой.",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["phone"] = v
            s["step"] = "confirm"
            inn = (data.get("inn") or "").strip()
            preview = (
                "Номер сохранён.\n\n"
                "📋 *Шаг 6/6: проверка данных*\n\n"
                f"🏢 Организация: {data.get('company_name', '')}\n"
                f"🧾 ИНН: {inn}\n"
                f"👤 Контактное лицо: {data.get('contact_name', '')}\n"
                f"💼 Должность: {data.get('position_in_org', '')}\n"
                f"📞 Телефон: {data.get('phone', '')}\n\n"
                "Всё верно?\n\n"
                "👇"
            )
            return {
                "text": preview,
                "format": "markdown",
                "attachments": visit_card.client_reg_confirm_keyboard(),
            }
        if step == "confirm":
            return {
                "text": "Используйте кнопки под сообщением: подтвердить или заполнить заново.\n\n👇",
                "format": "markdown",
                "attachments": visit_card.client_reg_confirm_keyboard(),
            }

    if flow == "question" and step == "text":
        if not data.get("question_consent_accepted"):
            return {
                "text": _consent_gate_text("вопрос менеджеру"),
                "format": "markdown",
                "attachments": visit_card.consent_gate_keyboard("question"),
            }
        qid = _new_id()
        plain = _format_question_plain(text, qid, who)
        await _notify_plain(f"Новый вопрос #{qid}", plain)
        username = (sender or {}).get("username") if isinstance(sender, dict) else ""
        try:
            save_visit_question(max_uid, str(username or ""), text)
        except Exception:
            logger.exception("save_visit_question")
        clear_session(max_uid)
        return {
            "text": "*Сообщение отправлено.* Спасибо!\n\n👇",
            "format": "markdown",
            "attachments": visit_card.main_menu_keyboard(),
        }

    if flow == "order":
        if step == "event_type":
            data["event_type"] = text.strip()
            s["step"] = "city"
            return {
                "text": "Укажите город проведения мероприятия.\n\n_Образец:_ `Москва`\n\n👇",
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "city":
            data["city"] = text.strip()
            s["step"] = "event_date"
            return {
                "text": (
                    "Укажите дату мероприятия или период (можно несколько дней).\n\n"
                    "_Образец:_ `15.06.2026` или `12–14 июня 2026`\n\n"
                    "👇"
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
                    "_После выбора нажмите «Готово»._\n\n"
                    "👇"
                ),
                "format": "markdown",
                "attachments": visit_card.order_staff_keyboard({}),
            }
        if step == "contact_phone":
            if not data.get("order_consent_accepted"):
                return {
                    "text": _consent_gate_text("заказ расчёта"),
                    "format": "markdown",
                    "attachments": visit_card.consent_gate_keyboard("order"),
                }
            v = validate_phone(text)
            if not v:
                return {
                    "text": "Неверный формат. Пример: +79001234567 или кнопка «Отправить контакт».",
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
                    "text": "Введите полное ФИО (минимум 2 слова, буквы и дефис). Пример: Иванов Иван Иванович",
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
            if not company or company == "—":
                return {
                    "text": "Название компании обязательно. Пример: ООО «Ромашка»",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["company_name"] = company
            s["step"] = "company_inn"
            return {
                "text": (
                    "Укажите ИНН компании (10 или 12 цифр).\n\n"
                    "_Образец:_ `7707083893`"
                ),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "company_inn":
            raw = text.strip()
            if not validate_inn(raw):
                return {
                    "text": "ИНН обязателен и должен содержать 10 или 12 цифр. Пример: 7707083893",
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
                "text": "Используйте кнопки под сообщением: отправить заявку или изменить данные.\n\n👇",
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
                    "Введите полное ФИО.\n\n"
                    "_Образец:_ `Иванов Иван Иванович`\n\n"
                    "👇"
                ),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "full_name":
            if not data.get("join_consent_accepted"):
                return {
                    "text": "Сначала подтвердите согласие на обработку данных.",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            if not validate_full_name(text):
                return {
                    "text": "ФИО: минимум 2 слова. Пример: Иванов Иван Иванович",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["full_name"] = text.strip()
            s["step"] = "phone"
            return {
                "text": (
                    "Отправьте телефон кнопкой или введите вручную.\n\n"
                    "_Образец:_ `+79001234567`\n\n"
                    "👇"
                ),
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
            s["step"] = "preferred_shift"
            return {
                "text": "Какие смены вам удобнее?\n\nВыберите один вариант.\n\n👇",
                "format": "markdown",
                "attachments": visit_card.join_shift_pref_keyboard(),
            }
        if step == "travel_radius":
            km = validate_radius_km(text)
            if km is None:
                return {
                    "text": "Укажите число от 0 до 200. Пример: 15",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["travel_radius_km"] = str(km)
            s["step"] = "docs_ready"
            return {
                "text": "Какие документы уже готовы?\n\n👇",
                "format": "markdown",
                "attachments": visit_card.join_docs_keyboard(),
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
                    "Дополнительные навыки и инструменты (языки, ПО, права, медкнижка и т.д.).\n\n"
                    "_Образец:_ `Английский B1, права кат. B, опыт работы с кассой`\n"
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
                    "Пришлите *селфи* для подтверждения анкеты (только фото, без текста).\n\n"
                    "Лицо должно быть хорошо видно."
                ),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "selfie":
            ref = _image_ref_from_body(message_body)
            if not ref:
                return {
                    "text": "Нужно отправить фото (селфи), не текст.",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["selfie_ref"] = ref
            data["portfolio_refs"] = []
            s["step"] = "portfolio"
            return {
                "text": (
                    "Добавьте мини-портфолио: 1–2 фото/видео с проектов.\n\n"
                    "Отправьте минимум 1 файл, затем нажмите *«Продолжить»*.\n\n"
                    "👇"
                ),
                "format": "markdown",
                "attachments": visit_card.join_portfolio_keyboard(),
            }
        if step == "portfolio":
            ref = _media_ref_from_body(message_body)
            if not ref:
                return {
                    "text": "Отправьте фото или видео. После этого нажмите «Продолжить».\n\n👇",
                    "format": "markdown",
                    "attachments": visit_card.join_portfolio_keyboard(),
                }
            refs = list(data.get("portfolio_refs") or [])
            if len(refs) >= 2:
                return {
                    "text": "Достаточно, уже получено 2 файла. Нажмите «Продолжить».\n\n👇",
                    "format": "markdown",
                    "attachments": visit_card.join_portfolio_keyboard(),
                }
            refs.append(ref)
            data["portfolio_refs"] = refs
            left = 2 - len(refs)
            if left > 0:
                txt = f"Файл получен ✅ Можно добавить ещё {left} или нажать «Продолжить».\n\n👇"
            else:
                txt = "Получено 2 файла ✅ Нажмите «Продолжить».\n\n👇"
            return {
                "text": txt,
                "format": "markdown",
                "attachments": visit_card.join_portfolio_keyboard(),
            }
        if step == "review_submit":
            return {
                "text": "Нажмите кнопку «Отправить анкету» ниже.\n\n👇",
                "format": "markdown",
                "attachments": visit_card.submit_join_keyboard(),
            }
        if step == "experience_years":
            return {
                "text": "Выберите стаж.\n\n👇",
                "format": "markdown",
                "attachments": visit_card.experience_keyboard(),
            }
        if step == "preferred_shift":
            return {
                "text": "Какие смены вам удобнее?\n\nВыберите один вариант.\n\n👇",
                "format": "markdown",
                "attachments": visit_card.join_shift_pref_keyboard(),
            }
        if step == "docs_ready":
            return {
                "text": "Какие документы уже готовы?\n\n👇",
                "format": "markdown",
                "attachments": visit_card.join_docs_keyboard(),
            }
        if step == "priority_pool":
            return {
                "text": "Выберите вариант кнопкой.\n\n👇",
                "format": "markdown",
                "attachments": visit_card.join_priority_keyboard(),
            }

    return None
