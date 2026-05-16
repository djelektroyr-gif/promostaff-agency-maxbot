"""
Сценарии FSM: заказ расчёта (как Telegram-визитка), вопрос менеджеру, анкета в команду.
Состояние в памяти. Уведомления — notify.notify_agency_admins.

Визитка: где уместно — явные офферы (супервайзер при 2+ в смене, менеджер для сметы/периода)
и короткий `notification` в ответах на callback — нативная обратная связь MAX.
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
import time
import json
from datetime import date
from typing import Any

from config import (
    CLIENT_POSITIONS,
    COMPANY_NAME,
    LISTING_PUBLICATION_FEE_RUB,
    SUPERVISOR_TM_LEAD,
    PRIVACY_POLICY_URL,
    TERMS_OF_SERVICE_URL,
    WEBSITE_URL,
    order_hourly_rates,
)

import visit_card
import visit_join_validators
from visit_join_anketa_catalog import (
    EXPERIENCE_RATING_TABLE,
    PROFESSION_SLUG_TO_TITLE,
    ProfessionCategory,
)
from funnel_store import funnel_touch_complete
from funnel_db import (
    has_max_active_executor_profile,
    is_max_visit_client_registered,
    is_max_visit_client_verified,
    is_max_visit_worker_verified,
    save_max_visit_client_verified,
    get_max_visit_client,
    save_visit_join,
    save_visit_order_payload,
    list_agency_visit_orders_for_user,
    save_visit_question,
)
from notify import notify_agency_admins
from shift_pricing import calculate_order_cost, parse_shift_interval

logger = logging.getLogger(__name__)


def _norm_cb_payload(payload: Any) -> str:
    """MAX может отдавать payload строкой или вложенным объектом; префиксы сравниваем без учёта регистра."""
    if payload is None:
        return ""
    if isinstance(payload, dict):
        return str(
            payload.get("payload")
            or payload.get("callback_payload")
            or payload.get("data")
            or ""
        ).strip()
    return str(payload).strip()


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
        + ""
    )


def clear_session(max_uid: int) -> None:
    SESSIONS.pop(max_uid, None)


def _phone_resolve_or_none(
    max_uid: int,
    session: dict[str, Any],
    phone: str,
    intended_role: str,
) -> dict[str, Any] | None:
    """После ввода телефона: резолв по БД; None — продолжить регистрацию."""
    from user_identity import resolve_registration_by_phone

    res = resolve_registration_by_phone(int(max_uid), phone, intended_role)  # type: ignore[arg-type]
    data = session.setdefault("data", {})
    if res.canonical_tg_id:
        data["canonical_user_tg_id"] = res.canonical_tg_id
    if res.action == "continue":
        return None
    clear_session(max_uid)
    if res.action.startswith("resume"):
        home = visit_card.message_role_home(max_uid)
        if res.text:
            home = dict(home)
            home["text"] = f"{res.text}\n\n{home.get('text', '')}"
        if res.notification:
            home["notification"] = res.notification
        return home
    return {
        "notification": res.notification,
        "text": res.text,
        "format": res.format,
        "attachments": visit_card.main_menu_keyboard(),
    }


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


def _order_contact_ready(data: dict) -> bool:
    return bool(
        (data.get("contact_phone") or "").strip()
        and (data.get("contact_name") or "").strip()
        and (data.get("contact_email") or "").strip()
        and (data.get("company_name") or "").strip()
        and (data.get("company_inn") or "").strip()
    )


def _hydrate_order_contact_from_visit(max_uid: int, data: dict) -> None:
    row = get_max_visit_client(max_uid)
    if not row:
        return
    if not (data.get("contact_phone") or "").strip() and row.get("phone"):
        v = validate_phone(row["phone"])
        if v:
            data["contact_phone"] = v
    if not (data.get("contact_name") or "").strip() and row.get("contact_name"):
        data["contact_name"] = row["contact_name"].strip()
    if not (data.get("company_name") or "").strip() and row.get("company_name"):
        data["company_name"] = row["company_name"].strip()
    inn = (row.get("inn") or "").strip()
    if inn and not (data.get("company_inn") or "").strip():
        data["company_inn"] = re.sub(r"\D", "", inn)
    if not (data.get("contact_email") or "").strip() and row.get("contact_email"):
        data["contact_email"] = row["contact_email"].strip()


def _advance_order_contact_step(
    max_uid: int, s: dict, *, notification: str | None = None
) -> dict[str, Any]:
    data = s.setdefault("data", {})
    _hydrate_order_contact_from_visit(max_uid, data)
    out: dict[str, Any] = {
        "format": "markdown",
        "attachments": visit_card.back_to_main_keyboard(),
    }
    if notification:
        out["notification"] = notification
    if _order_contact_ready(data):
        if (data.get("order_kind") or "").strip() == "vacancy_listing":
            ch = (data.get("contact_channel") or "").strip()
            if ch not in ("call", "max_chat", "email"):
                s["step"] = "contact_channel_pick"
                out["text"] = "Как удобнее связаться по объявлению?"
                out["attachments"] = visit_card.order_contact_channel_keyboard()
                return out
            if ch == "call" and not (data.get("call_time") or "").strip():
                s["step"] = "call_time"
                out["text"] = (
                    "Когда удобно принять звонок менеджера?\n\n"
                    "_Образец:_ `будни 10:00–18:00`"
                )
                return out
            s["step"] = "listing_confirm"
            out["text"] = _listing_preview_text(data)
            out["attachments"] = visit_card.listing_confirm_keyboard()
            return out
        s["step"] = "call_time"
        out["text"] = (
            "Когда удобно принять звонок менеджера?\n\n"
            "_Образец:_ `будни 10:00–18:00`"
        )
        return out
    if not (data.get("contact_phone") or "").strip():
        s["step"] = "contact_phone"
        out["text"] = (
            "Отправьте контакт телефона кнопкой ниже или введите вручную.\n\n"
            "_Образец:_ `+79001234567`\n\n"
        )
        return out
    if not (data.get("contact_name") or "").strip():
        s["step"] = "contact_name"
        out["text"] = "Введите полное ФИО.\n\n_Образец:_ `Иванов Иван Иванович`"
        return out
    if not (data.get("contact_email") or "").strip():
        s["step"] = "contact_email"
        out["text"] = "Введите email для связи.\n\n_Образец:_ `client@company.ru`"
        return out
    if not (data.get("company_name") or "").strip():
        s["step"] = "company_name"
        out["text"] = (
            "Укажите название компании (или `—` если нет).\n\n"
            "_Образец:_ `ООО «Ромашка»`"
        )
        return out
    if not (data.get("company_inn") or "").strip():
        s["step"] = "company_inn"
        out["text"] = (
            "Укажите ИНН компании (10 или 12 цифр).\n\n"
            "_Образец:_ `7707083893`"
        )
        return out
    s["step"] = "call_time"
    out["text"] = (
        "Когда удобно принять звонок менеджера?\n\n"
        "_Образец:_ `будни 10:00–18:00`"
    )
    return out


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


def _brief_file_from_body(message_body: dict[str, Any] | None) -> dict[str, str] | None:
    """Первое файловое вложение в сообщении MAX (url + имя)."""
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
        url = ""
        if isinstance(p, dict):
            for key in ("url", "photo_url", "small_url", "medium_url", "token"):
                v = p.get(key)
                if v:
                    url = str(v)
                    break
        elif isinstance(p, str) and p:
            url = p
        if not url:
            continue
        name = ""
        if isinstance(p, dict):
            name = str(p.get("filename") or p.get("name") or p.get("title") or "")
        if not name:
            name = f"attachment.{t}" if t in ("image", "photo", "picture") else "file"
        return {"url": url, "name": name, "kind": t}
    return None


def _message_body_has_video(message_body: dict[str, Any] | None) -> bool:
    if not message_body:
        return False
    raw = message_body.get("attachments")
    if raw is None and isinstance(message_body.get("attachment"), dict):
        raw = [message_body["attachment"]]
    if not isinstance(raw, list):
        return False
    for a in raw:
        if isinstance(a, dict) and (a.get("type") or "").lower() == "video":
            return True
    return False


def _portfolio_photo_ref_from_body(message_body: dict[str, Any] | None) -> str | None:
    """Ссылка на изображение для портфолио (без видео и произвольных файлов)."""
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
        if t not in ("image", "photo", "picture"):
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
    f"vac_apply_{slug}": title
    for slug, title in (
        ("helper", "Хелпер"),
        ("loader", "Грузчик"),
        ("promoter", "Промоутер"),
        ("hostess", "Хостес"),
        ("animator", "Аниматор"),
        ("barista", "Бариста"),
        ("bartender", "Бармен"),
        ("waiter", "Официант"),
        ("cashier", "Кассир"),
        ("chef_head", "Шеф-повар"),
        ("cook", "Повар"),
        ("dishwasher", "Мойщик посуды"),
        ("cleaner", "Уборщик"),
        ("cloakroom", "Гардеробщик"),
        ("security", "Охранник"),
        ("parking", "Парковщик"),
        ("driver", "Водитель"),
        ("shuttle_driver", "Шаттл-водитель"),
        ("supervisor", "Супервайзер"),
    )
}


def _join_entry_blocked(max_uid: int) -> dict[str, Any] | None:
    if is_max_visit_client_registered(max_uid):
        return {
            "notification": "Недоступно",
            "text": (
                "Вы зарегистрированы как заказчик. Анкета исполнителя для этого аккаунта недоступна.\n\n"
                "_Смена роли — через администратора._"
            ),
            "format": "markdown",
            "attachments": visit_card.main_menu_keyboard(),
        }
    if has_max_active_executor_profile(max_uid):
        if is_max_visit_worker_verified(max_uid):
            return {
                "notification": "Уже в команде",
                "text": "У вас уже есть профиль исполнителя. Откройте главное меню.",
                "format": "markdown",
                "attachments": visit_card.worker_registered_main_menu_keyboard(),
            }
        return {
            "notification": "На проверке",
            "text": (
                "*Анкета уже отправлена.*\n\n"
                "Дождитесь подтверждения администратором — затем откроется меню исполнителя."
            ),
            "format": "markdown",
            "attachments": visit_card.worker_pending_verification_keyboard(),
        }
    return None


def _gate_client_quote_access(max_uid: int) -> dict[str, Any] | None:
    """Расчёт/КП/объявление — только после admin-verify заказчика (как TG begin_client_quote_flow)."""
    from user_identity import ROLE_SWITCH_VIA_ADMIN_FOOTER_RU

    if has_max_active_executor_profile(max_uid):
        return {
            "notification": "Недоступно",
            "text": (
                "Исполнителям недоступен заказ расчёта как заказчику. "
                "Откройте главное меню."
                + ROLE_SWITCH_VIA_ADMIN_FOOTER_RU
            ),
            "format": "markdown",
            "attachments": visit_card.main_menu_keyboard(),
        }
    if is_max_visit_client_verified(max_uid):
        return None
    if is_max_visit_client_registered(max_uid):
        return {
            "notification": "Ожидает проверки",
            "text": (
                "*Регистрация заказчика на проверке*\n\n"
                "Расчёты, КП и объявления доступны после подтверждения профиля администратором.\n\n"
                "Пока можете связаться с менеджером."
            ),
            "format": "markdown",
            "attachments": visit_card.client_pre_erp_pending_keyboard(),
        }
    return {
        "notification": "Нужна регистрация",
        "text": (
            "Сначала пройдите *регистрацию заказчика* (юрлицо) через «Меню заказчика» в визитке."
        ),
        "format": "markdown",
        "attachments": visit_card.main_menu_keyboard(),
    }


def start_client_visit_menu(max_uid: int) -> dict[str, Any]:
    """«Меню заказчика» — только регистрация, без заявок до verify (паритет TG client_visit_menu)."""
    from user_identity import ROLE_SWITCH_VIA_ADMIN_FOOTER_RU

    clear_session(max_uid)
    if has_max_active_executor_profile(max_uid):
        return {
            "notification": "Недоступно",
            "text": (
                "Исполнителям недоступен вход как заказчику. Откройте главное меню."
                + ROLE_SWITCH_VIA_ADMIN_FOOTER_RU
            ),
            "format": "markdown",
            "attachments": visit_card.main_menu_keyboard(),
        }
    if is_max_visit_client_registered(max_uid):
        if is_max_visit_client_verified(max_uid):
            home = visit_card.message_role_home(max_uid)
            home["notification"] = "Уже зарегистрированы"
            if home.get("text"):
                home["text"] = (
                    "У вас уже есть профиль заказчика — меню ниже.\n\n" + home["text"]
                )
            return home
        return _gate_client_quote_access(max_uid) or {}
    SESSIONS[max_uid] = {"flow": "client_visit", "step": "consent", "data": {}}
    return {
        "notification": "Меню заказчика",
        "text": _client_visit_entry_text(),
        "format": "markdown",
        "attachments": visit_card.consent_gate_keyboard("client_visit"),
    }


def route_calculate_button(max_uid: int) -> dict[str, Any]:
    """Старые кнопки «Заказать расчёт» → регистрация или меню заказчика, не заявка без verify."""
    if is_max_visit_client_verified(max_uid):
        return start_client_quote(max_uid)
    if is_max_visit_client_registered(max_uid):
        return _gate_client_quote_access(max_uid) or start_client_visit_menu(max_uid)
    return start_client_visit_menu(max_uid)


def start_client_quote(max_uid: int, *, preset: str | None = None) -> dict[str, Any]:
    """Заявка на расчёт/КП/listing после верификации заказчика."""
    blocked = _gate_client_quote_access(max_uid)
    if blocked:
        return blocked
    if preset == "listing":
        return start_listing_order(max_uid)
    clear_session(max_uid)
    SESSIONS[max_uid] = {
        "flow": "order",
        "step": "order_mode",
        "data": {"order_consent_accepted": True},
    }
    if preset == "quick":
        SESSIONS[max_uid]["step"] = "event_type"
        return {
            "notification": "Срочный расчёт",
            "text": (
                "*Срочный расчёт*\n\n"
                "Выберите быстрый сценарий или введите тип проекта вручную.\n\n"
            ),
            "format": "markdown",
            "attachments": visit_card.order_quickstart_keyboard(),
        }
    if preset == "cp":
        SESSIONS[max_uid]["data"]["order_kind"] = "cp_request"
        SESSIONS[max_uid]["step"] = "cp_event_type"
        return {
            "notification": "Запрос КП",
            "text": (
                "*Запрос коммерческого предложения*\n\n"
                "Опишите *тип мероприятия* (выставка, промо, корпоратив и т.д.).\n\n"
                "_Образец:_ `Корпоратив, 200 гостей, Москва-Сити`\n\n"
            ),
            "format": "markdown",
            "attachments": visit_card.cp_step_keyboard(),
        }
    return start_order(max_uid, announce_order_consent=False)


def start_listing_order(max_uid: int) -> dict[str, Any]:
    """Размещение объявления в ленте (vacancy_listing)."""
    blocked = _gate_client_quote_access(max_uid)
    if blocked:
        return blocked
    fee = int(LISTING_PUBLICATION_FEE_RUB)
    fee_md = f"{fee:,}".replace(",", " ")
    SESSIONS[max_uid] = {
        "flow": "order",
        "step": "listing_position",
        "data": {
            "order_kind": "vacancy_listing",
            "order_consent_accepted": True,
            "listing_publication_fee_rub": fee,
        },
    }
    return {
        "notification": "Объявление",
        "text": (
            "*Разместить объявление*\n\n"
            "Заявка на публикацию в ленте для исполнителей агентства. "
            f"Ориентир тарифа: *{fee_md}* ₽ (итог — в счёте от менеджера). "
            "В эфир — после оплаты и подтверждения.\n\n"
            "Шаг 1 из 4. Укажите *роль или задачу* в одной строке.\n\n"
            "_Образец:_ `Промоутеры на дегустацию в ТЦ`"
        ),
        "format": "markdown",
        "attachments": visit_card.order_flow_back_keyboard(),
    }


def start_order(max_uid: int, *, announce_order_consent: bool = True) -> dict[str, Any]:
    """Выбор режима заявки — только для верифицированного заказчика."""
    clear_session(max_uid)
    blocked = _gate_client_quote_access(max_uid)
    if blocked:
        return blocked
    SESSIONS[max_uid] = {
        "flow": "order",
        "step": "order_mode",
        "data": {"order_consent_accepted": True},
    }
    msg: dict[str, Any] = {
        "text": (
            "*Заказ расчёта стоимости*\n\n"
            "*Срочный расчёт* — оценка по одной типичной смене прямо в боте.\n"
            "*Коммерческое предложение* — менеджер подготовит КП по вашим вводным.\n"
            "*Разместить объявление* — публикация вакансии в ленте для исполнителей.\n\n"
            "Выберите вариант:"
        ),
        "format": "markdown",
        "attachments": visit_card.order_mode_keyboard(),
    }
    if announce_order_consent:
        msg["notification"] = " "
    return msg


def start_fill_anketa(max_uid: int) -> dict[str, Any]:
    """Запуск полной анкеты исполнителя прямо в MAX-визитке."""
    blocked = _join_entry_blocked(max_uid)
    if blocked:
        return blocked
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
        "data": {"join_entry": "profile"},
    }
    return {
        "text": _consent_gate_text("отклик в команду"),
        "format": "markdown",
        "attachments": visit_card.consent_gate_keyboard("join"),
    }


def join_from_vacancy(max_uid: int, payload: str) -> dict[str, Any] | None:
    blocked = _join_entry_blocked(max_uid)
    if blocked:
        return blocked
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


def _basic_info_intro() -> str:
    return (
        "*ОСНОВНАЯ ИНФОРМАЦИЯ*\n\n"
        "Для получения предложений о сменах заполните анкету.\n\n"
        "Чем подробнее вы заполните профиль, тем точнее будут предложения.\n\n"
        "Давайте знакомиться — введите ваше *ФИО*.\n\n"
        "_Пример: Иванов Иван Иванович_"
    )


def _join_prompt_experience() -> dict[str, Any]:
    return {
        "text": (
            "*ОПЫТ РАБОТЫ*\n"
            "*Общий опыт работы в выбранной сфере:*"
            f"{EXPERIENCE_RATING_TABLE}"
        ),
        "format": "markdown",
        "attachments": visit_card.experience_level_keyboard(),
    }


def _join_parse_birth_from_data(data: dict[str, Any]) -> date | None:
    br = data.get("birth_date")
    if not br:
        return None
    try:
        return date.fromisoformat(str(br)[:10])
    except ValueError:
        return visit_join_validators.parse_birth_date(str(br))


def _join_prompt_snils() -> dict[str, Any]:
    return {
        "text": (
            "🪪 *СНИЛС*\n\n"
            "Укажите номер страхового свидетельства ОПС — *11 цифр*. "
            "Можно с дефисами и пробелом, как на зелёной карточке или в Госуслугах.\n\n"
            "_Пример: 112-233-445 95_"
        ),
        "format": "markdown",
        "attachments": visit_card.back_to_main_keyboard(),
    }


def _join_begin_identity_chain(s: dict[str, Any]) -> dict[str, Any]:
    s["step"] = "snils"
    return _join_prompt_snils()


def _join_begin_tbank_gate(s: dict[str, Any]) -> dict[str, Any]:
    kb = visit_card.tbank_cabinet_gate_keyboard()
    plain = visit_card.tbank_self_employed_invite_plain()
    if not kb or not plain:
        return _join_begin_identity_chain(s)
    s["step"] = "tbank_cabinet"
    return {
        "text": plain,
        "format": "markdown",
        "attachments": kb,
    }


def _join_prompt_portfolio_menu() -> dict[str, Any]:
    return {
        "text": (
            "📁 *ПОРТФОЛИО*\n\n"
            "Если есть портфолио — отправьте *PDF-презентацию* или *ссылку* "
            "(Behance, сайт, облако — только *https://*).\n\n"
            "Шаг можно пропустить."
        ),
        "format": "markdown",
        "attachments": visit_card.join_portfolio_menu_keyboard(),
    }


def _join_prompt_selfie() -> dict[str, Any]:
    return {
        "text": (
            "*📸 СЕЛФИ*\n\n"
            "Для верификации личности отправьте своё актуальное селфи (фото лица).\n\n"
            "_Нажмите на скрепку 📎 → Камера, чтобы сделать фото._\n\n"
            "💡 _Фото должно быть чётким, лицо полностью видно, без солнцезащитных очков и масок._"
        ),
        "format": "markdown",
        "attachments": visit_card.back_to_main_keyboard(),
    }


def _join_go_to_review(s: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    s["step"] = "review_submit"
    return {
        "text": _build_join_review_text(data),
        "format": "markdown",
        "attachments": visit_card.join_review_keyboard(),
    }


def _join_portfolio_review_line(data: dict[str, Any]) -> str:
    mode = str(data.get("portfolio_mode") or "none").strip().lower()
    if mode == "pdf":
        ref = (data.get("portfolio_pdf_file_id") or "").strip()
        return "PDF" if ref else "— (PDF не прикреплён)"
    if mode == "url":
        u = (data.get("portfolio_url") or "").strip()
        return u or "—"
    return "нет"


def _build_join_tags(data: dict[str, Any]) -> str:
    parts = [
        (data.get("position") or "").strip(),
        (data.get("profession_category") or "").strip(),
        (data.get("tax_status_label") or "").strip(),
    ]
    return "; ".join(p for p in parts if p)


def _build_join_review_text(data: dict[str, Any]) -> str:
    m = "—"
    bonus = int(data.get("anketa_bonus_star") or 0)
    base = int(data.get("experience_base_stars") or 0)
    max_stars = base + bonus
    return (
        "*Завершение регистрации*\n\n"
        "Проверьте данные перед отправкой:\n\n"
        f"*ФИО:* {data.get('full_name') or m}\n"
        f"*Телефон:* {data.get('phone') or m}\n"
        f"*Дата рождения:* {data.get('birth_date') or m}\n"
        f"*Профессия:* {data.get('position') or m}\n"
        f"*Категория:* {data.get('profession_category') or m}\n"
        f"*Налоговый статус:* {data.get('tax_status_label') or m}\n"
        f"*ИНН:* {data.get('tax_inn') or m}\n"
        f"*Опыт:* {data.get('experience_years') or m} (база {base}⭐, с анкетой до {max_stars}⭐)\n"
        f"*Описание опыта:* {data.get('experience_desc') or m}\n"
        f"*Рост / вес:* {data.get('height_cm') or m} / {data.get('weight_kg') or m}\n"
        f"*Пол / одежда / обувь:* {data.get('gender') or m} / {data.get('clothing_size') or m} / "
        f"{data.get('shoe_size') or m}\n"
        f"*Форма:* {data.get('uniform_choice_label') or m}\n"
        f"*Медкнижка:* {data.get('medbook_label') or m}\n"
        f"*Командировки:* {data.get('trips_label') or m}\n"
        f"*СНИЛС:* {data.get('snils') or m}\n"
        f"*E-mail:* {data.get('contact_email') or m}\n"
        f"*Банк:* {data.get('gph_bank_name') or m}\n"
        f"*БИК:* {data.get('gph_bik') or m}\n"
        f"*Р/с:* {data.get('gph_settlement_account') or m}\n"
        f"*К/с:* {data.get('gph_corr_account') or m}\n"
        f"*Навыки:* {data.get('skills') or m}\n"
        f"*Портфолио:* {_join_portfolio_review_line(data)}\n"
        f"*Паспорт:* {data.get('passport_sn') or m}\n"
        f"*Кем выдан:* {data.get('passport_issued_by') or m}\n"
        f"*Дата выдачи:* {data.get('passport_issued_on') or m}\n"
        f"*Адрес регистрации:* {data.get('registration_address') or m}\n"
        f"*Город работы:* {data.get('city') or m}\n"
        f"*Метро:* {data.get('metro_station') or m}\n\n"
        "Нажмите кнопку ниже."
    )


def _align_join_payload_for_pg(data: dict[str, Any]) -> dict[str, Any]:
    out = dict(data)
    if out.get("selfie_ref") and not out.get("selfie_url"):
        out["selfie_url"] = out["selfie_ref"]
    if out.get("tax_cert_ref") and not out.get("tax_cert_file_id"):
        out["tax_cert_file_id"] = out["tax_cert_ref"]
    if out.get("tax_ip_doc_ref") and not out.get("tax_ip_doc_file_id"):
        out["tax_ip_doc_file_id"] = out["tax_ip_doc_ref"]
    if out.get("passport_main_ref") and not out.get("passport_main_file_id"):
        out["passport_main_file_id"] = out["passport_main_ref"]
    if out.get("passport_reg_ref") and not out.get("passport_reg_file_id"):
        out["passport_reg_file_id"] = out["passport_reg_ref"]
    if out.get("portfolio_pdf_ref") and not out.get("portfolio_pdf_file_id"):
        out["portfolio_pdf_file_id"] = out["portfolio_pdf_ref"]
    return out


def _join_tax_callbacks(s: dict[str, Any], payload: str) -> dict[str, Any] | None:
    flow = s.get("flow")
    step = s.get("step")
    if flow != "join":
        return None
    data = s.setdefault("data", {})

    if payload == "tax_back_bd" and step == "tax_menu":
        s["step"] = "birth_date"
        return {
            "notification": "Шаг назад",
            "text": "🎂 *Дата рождения:*\n\n_Пример: 15.05.1990_",
            "format": "markdown",
            "attachments": visit_card.back_to_main_keyboard(),
        }

    if payload == "tax_fl" and step == "tax_menu":
        data["tax_status"] = "fl"
        data["tax_status_label"] = "Физическое лицо"
        s["step"] = "tax_fl_menu"
        return {
            "notification": "Физлицо",
            "text": visit_card.text_tax_fl_disclaimer(),
            "format": "markdown",
            "attachments": visit_card.tax_fl_followup_keyboard(),
        }

    if payload == "tax_se" and step == "tax_menu":
        data["tax_status"] = "se"
        data["tax_status_label"] = "Самозанятый"
        s["step"] = "tax_se_inn"
        return {
            "notification": "Самозанятый",
            "text": (
                "*Вы выбрали статус «Самозанятый».*\n\n"
                "Введите ваш *ИНН* (10 или 12 цифр).\n\n"
                "Затем пришлите *справку о постановке на учёт* из приложения «Мой налог».\n\n"
                "_Это нужно для подтверждения статуса самозанятого в системе._"
                + visit_card.tbank_self_employed_invite_md()
            ),
            "format": "markdown",
            "attachments": visit_card.back_to_main_keyboard(),
        }

    if payload == "tax_ip" and step == "tax_menu":
        data["tax_status"] = "ip"
        data["tax_status_label"] = "ИП"
        s["step"] = "tax_ip_inn"
        return {
            "notification": "ИП",
            "text": (
                "*Вы выбрали статус «Индивидуальный предприниматель».*\n\n"
                "Введите ваш *ИНН*.\n\n"
                "Затем пришлите *выписку из ЕГРИП* о постановке на учёт в качестве ИП.\n\n"
                "_Это нужно для подтверждения статуса ИП в системе._"
            ),
            "format": "markdown",
            "attachments": visit_card.back_to_main_keyboard(),
        }

    if payload == "tax_help" and step == "tax_fl_menu":
        data["tax_status"] = "se"
        data["tax_status_label"] = "Самозанятый (оформление)"
        s["step"] = "tax_help_cert"
        return {
            "notification": "Помощь",
            "text": visit_card.text_tax_self_help(),
            "format": "markdown",
            "attachments": visit_card.tax_se_actions_keyboard(),
        }

    if payload == "tax_help" and step == "tax_menu":
        data["tax_status"] = "se_help"
        data["tax_status_label"] = "Самозанятый (помощь)"
        s["step"] = "tax_help_cert"
        return {
            "notification": "Помощь",
            "text": visit_card.text_tax_self_help(),
            "format": "markdown",
            "attachments": visit_card.tax_se_actions_keyboard(),
        }

    if payload == "tax_fl_go" and step == "tax_fl_menu":
        s["step"] = "tax_fl_inn"
        return {
            "notification": "Физлицо",
            "text": (
                "👤 *ИНН физического лица*\n\n"
                "Укажите ваш *ИНН* — *12 цифр* (как в документах ФНС или в личном кабинете налогоплательщика).\n\n"
                "_Нужен для договоров и учёта НДФЛ 13%._\n\n"
                "_После ИНН перейдём к СНИЛС и реквизитам для выплат._"
            ),
            "format": "markdown",
            "attachments": visit_card.back_to_main_keyboard(),
        }

    if payload == "tax_back_status" and step == "tax_fl_menu":
        s["step"] = "tax_menu"
        return {
            "notification": "Назад",
            "text": visit_card.text_tax_status_intro(),
            "format": "markdown",
            "attachments": visit_card.join_tax_status_keyboard(),
        }

    if payload == "tax_back_status" and step in ("tax_se_cert", "tax_help_cert", "tax_ip_cert"):
        data.pop("tax_cert_ref", None)
        data.pop("tax_ip_doc_ref", None)
        s["step"] = "tax_menu"
        return {
            "notification": "Назад",
            "text": visit_card.text_tax_status_intro(),
            "format": "markdown",
            "attachments": visit_card.join_tax_status_keyboard(),
        }

    if payload == "tax_upload_cert" and step in ("tax_se_cert", "tax_help_cert", "tax_ip_cert"):
        att = (
            visit_card.tax_ip_actions_keyboard()
            if step == "tax_ip_cert"
            else visit_card.tax_se_actions_keyboard()
        )
        hint = (
            "Пришлите *выписку* вложением (фото или файл). Затем нажмите «Отправить на проверку»."
            if step == "tax_ip_cert"
            else "Пришлите *справку* вложением (фото или файл). Затем нажмите «Отправить на проверку»."
        )
        return {
            "notification": "Пришлите файл или фото в чат",
            "text": hint,
            "format": "markdown",
            "attachments": att,
        }

    if payload == "tax_se_send" and step in ("tax_se_cert", "tax_help_cert"):
        if not data.get("tax_cert_ref"):
            return {
                "notification": "Сначала загрузите справку",
                "text": "Пришлите справку вложением, затем нажмите кнопку снова.",
                "format": "markdown",
                "attachments": visit_card.tax_se_actions_keyboard(),
            }
        if data.get("tax_status") == "se_help":
            data["tax_status"] = "se"
            data["tax_status_label"] = "Самозанятый"
        return {"notification": "Принято ✅", **_join_begin_tbank_gate(s)}

    if payload == "tax_ip_send" and step == "tax_ip_cert":
        if not data.get("tax_ip_doc_ref"):
            return {
                "notification": "Сначала загрузите выписку",
                "text": "Пришлите выписку вложением, затем нажмите кнопку снова.",
                "format": "markdown",
                "attachments": visit_card.tax_ip_actions_keyboard(),
            }
        return {"notification": "Принято ✅", **_join_begin_identity_chain(s)}

    return None


def _format_join_plain(data: dict[str, Any], rid: int, who: str) -> str:
    m = "—"
    birth = (data.get("birth_date") or "").strip() or m
    tax_lbl = (data.get("tax_status_label") or "").strip() or m
    tax_inn = (data.get("tax_inn") or "").strip() or m
    cert = (data.get("tax_cert_file_id") or data.get("tax_cert_ref") or "").strip() or m
    ip_doc = (data.get("tax_ip_doc_file_id") or data.get("tax_ip_doc_ref") or "").strip() or m
    selfie = (data.get("selfie_url") or data.get("selfie_ref") or "").strip() or m
    passport_sn = (data.get("passport_sn") or "").strip() or m
    pm = (data.get("passport_main_file_id") or data.get("passport_main_ref") or "").strip() or m
    pr = (data.get("passport_reg_file_id") or data.get("passport_reg_ref") or "").strip() or m
    bs = data.get("experience_base_stars")
    rating_line = f"{bs}⭐" if isinstance(bs, int) else m
    lines = [
        f"Новая заявка в команду #{rid}",
        "",
        f"От: {who}",
        "",
        "СОИСКАТЕЛЬ",
        f"- ФИО: {data.get('full_name') or m}",
        f"- Телефон: {data.get('phone') or m}",
        f"- Дата рождения: {birth}",
        f"- Профессия: {data.get('position') or m}",
        f"- Категория: {data.get('profession_category') or m}",
        f"- Налоговый статус: {tax_lbl}",
        f"- ИНН: {tax_inn}",
        f"- Справка НПД (ссылка): {cert}",
        f"- Выписка ИП (ссылка): {ip_doc}",
        f"- Базовый рейтинг (опыт): {rating_line}",
        f"- Уровень опыта: {data.get('experience_years') or m}",
        f"- Описание опыта: {data.get('experience_desc') or m}",
        f"- Рост/вес: {data.get('height_cm') or m}/{data.get('weight_kg') or m}",
        f"- Пол: {data.get('gender') or m}",
        f"- Размер одежды: {data.get('clothing_size') or m}",
        f"- Размер обуви: {data.get('shoe_size') or m}",
        f"- Форма: {data.get('uniform_choice_label') or m}",
        f"- Медкнижка: {data.get('medbook_label') or m}",
        f"- Командировки: {data.get('trips_label') or m}",
        f"- СНИЛС: {data.get('snils') or m}",
        f"- E-mail: {data.get('contact_email') or m}",
        f"- Банк: {data.get('gph_bank_name') or m}",
        f"- БИК: {data.get('gph_bik') or m}",
        f"- Р/с: {data.get('gph_settlement_account') or m}",
        f"- К/с: {data.get('gph_corr_account') or m}",
        f"- Навыки: {(data.get('skills') or '').strip() or m}",
        f"- Портфолио: {_join_portfolio_review_line(data)}",
        f"- Паспорт: {passport_sn}",
        f"- Кем выдан: {data.get('passport_issued_by') or m}",
        f"- Дата выдачи: {data.get('passport_issued_on') or m}",
        f"- Адрес рег.: {data.get('registration_address') or m}",
        f"- Город: {data.get('city') or m}",
        f"- Метро: {data.get('metro_station') or m}",
        f"- Селфи (ссылка): {selfie}",
        f"- Паспорт фото (гл.): {pm}",
        f"- Паспорт фото (прописка): {pr}",
        "",
        f"Теги: {(data.get('specialization_tags') or '').strip() or m}",
        f"Тег опыта: {(data.get('experience_tag') or '').strip() or m}",
        "",
        f"---\n{COMPANY_NAME}\nСайт: {WEBSITE_URL}\n",
    ]
    return "\n".join(lines)


async def _notify_plain(subject: str, plain: str) -> None:
    try:
        await notify_agency_admins(subject, plain)
    except Exception:
        logger.exception("notify_agency_admins failed")


def _schedule_notify(subject: str, plain: str) -> None:
    """Не блокировать ответ пользователю в MAX: SMTP/Telegram к админам — в фоне."""
    asyncio.create_task(_notify_plain(subject, plain))


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
        + ""
    )


def _cp_channel_label(ch: str) -> str:
    return {
        "call": "Звонок",
        "max_chat": "Сообщение в мессенджере (MAX)",
        "email": "Email",
    }.get(ch or "", ch or "—")


def _listing_preview_text(data: dict[str, Any]) -> str:
    try:
        fee = int(data.get("listing_publication_fee_rub") or LISTING_PUBLICATION_FEE_RUB)
    except (TypeError, ValueError):
        fee = int(LISTING_PUBLICATION_FEE_RUB)
    co = (data.get("company_name") or "").strip() or "—"
    inn = (data.get("company_inn") or "").strip() or "—"
    ch = _cp_channel_label(str(data.get("contact_channel") or ""))
    call_extra = ""
    if data.get("contact_channel") == "call":
        call_extra = f"\n• Удобное время звонка: {data.get('call_time') or '—'}"
    return (
        "*Проверьте заявку на размещение объявления*\n\n"
        f"_Ориентир тарифа публикации: {fee} ₽. Итог — в счёте от менеджера. "
        "Публикация — после оплаты и подтверждения._\n\n"
        "*Объявление*\n"
        f"• Роль / задача: {data.get('listing_role') or '—'}\n"
        f"• Город: {data.get('city') or '—'}\n"
        f"• Описание: {data.get('listing_description') or '—'}\n"
        f"• Срок / когда нужны люди: {data.get('event_date') or '—'}\n\n"
        "*Клиент*\n"
        f"• ФИО: {data.get('contact_name') or '—'}\n"
        f"• Компания: {co}\n"
        f"• ИНН: {inn}\n"
        f"• Телефон: {data.get('contact_phone') or '—'}\n"
        f"• Email: {data.get('contact_email') or '—'}\n\n"
        "*Связь*\n"
        f"• Предпочтительно: {ch}{call_extra}\n\n"
        "После отправки менеджер свяжется и подтвердит следующие шаги."
    )


def _format_listing_plain(data: dict[str, Any], oid: int, who: str) -> str:
    role = (data.get("listing_role") or "").strip()
    return (
        f"Новая заявка на объявление #{oid}\n"
        f"Клиент: {who}\n"
        f"Роль: {role}\n"
        f"Город: {data.get('city')}\n"
        f"Описание: {(data.get('listing_description') or '')[:500]}\n"
        f"Срок: {data.get('event_date')}\n"
        f"Телефон: {data.get('contact_phone')}\n"
        f"Email: {data.get('contact_email')}\n"
    )


def _cp_preview_text(data: dict[str, Any]) -> str:
    co = (data.get("company_name") or "").strip() or "—"
    inn = (data.get("company_inn") or "").strip() or "—"
    brief = (data.get("cp_brief_note") or "").strip() or "—"
    if data.get("cp_brief_has") is False:
        brief = "нет"
    elif data.get("cp_brief_max_url"):
        fn = (data.get("cp_brief_file_name") or "").strip() or "вложение"
        if not (data.get("cp_brief_note") or "").strip():
            brief = f"файл: {fn}"
        else:
            brief = f"{brief}; файл: {fn}"
    ch = _cp_channel_label(str(data.get("cp_contact_channel") or ""))
    call_extra = ""
    if data.get("cp_contact_channel") == "call":
        call_extra = f"\n• Удобное время звонка: {data.get('cp_call_time') or '—'}"
    return (
        "*Проверьте заявку на коммерческое предложение*\n\n"
        "*Клиент*\n"
        f"• ФИО: {data.get('contact_name')}\n"
        f"• Компания: {co}\n"
        f"• ИНН: {inn}\n"
        f"• Телефон: {data.get('contact_phone')}\n"
        f"• Email: {data.get('contact_email')}\n\n"
        "*Проект*\n"
        f"• Тип мероприятия: {data.get('event_type')}\n"
        f"• Город: {data.get('city')}\n"
        f"• Даты: {data.get('event_date')}\n"
        f"• Бриф / ТЗ: {brief}\n\n"
        "*Связь*\n"
        f"• Предпочтительно: {ch}"
        f"{call_extra}\n\n"
        "После отправки менеджер подготовит КП."
    )


def _format_cp_plain(data: dict[str, Any], who: str) -> str:
    ref = (data.get("public_ref") or "").strip() or "—"
    brief = (data.get("cp_brief_note") or "").strip() or "—"
    if data.get("cp_brief_has") is False:
        brief = "нет"
    file_line = ""
    if data.get("cp_brief_max_url"):
        file_line = f"Вложение: {data.get('cp_brief_file_name') or 'файл'}\n{data.get('cp_brief_max_url')}\n"
    ch = _cp_channel_label(str(data.get("cp_contact_channel") or ""))
    call_line = ""
    if data.get("cp_contact_channel") == "call":
        call_line = f"Удобное время звонка: {data.get('cp_call_time') or '—'}\n"
    return (
        f"НОВАЯ ЗАЯВКА НА КП ({ref})\n"
        f"================================\n\n"
        f"От: {who}\n\n"
        f"Тип: {data.get('event_type', '—')}\n"
        f"Город: {data.get('city', '—')}\n"
        f"Даты: {data.get('event_date', '—')}\n"
        f"Бриф: {brief}\n"
        f"Связь: {ch}\n"
        f"{call_line}\n"
        f"КЛИЕНТ\n"
        f"ФИО: {data.get('contact_name', '—')}\n"
        f"Компания: {data.get('company_name', '—')}\n"
        f"ИНН: {data.get('company_inn', '—')}\n"
        f"Телефон: {data.get('contact_phone', '—')}\n"
        f"Email: {data.get('contact_email', '—')}\n"
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
        )
    return (
        "*Супервайзер / тимлидер*\n\n"
        f"При *{total}* сотрудниках обычно нужен *{rec}* супервайзер(ов) — "
        "ориентир *около одного на каждые 5* человек.\n\n"
        "Ориентировочно *900* ₽/ч в дневное окно 10:00–22:00; ночные часы смены — "
        "*+15%* к часу (как у остальных ролей).\n\n"
        "Включите супервайзеров в предварительный расчёт или оставьте только исполнителей — "
        "точный состав уточнит менеджер.\n\n"
    )


def registered_menu_static_reply(max_uid: int, payload: str) -> dict[str, Any] | None:
    """Меню заказчика/исполнителя без активной SESSION (после clear_session)."""
    from funnel_db import (
        is_max_visit_client_verified,
        is_max_visit_worker_verified,
        list_agency_visit_orders_for_user,
    )

    if payload == "client_reg_projects":
        if is_max_visit_client_registered(max_uid) and not is_max_visit_client_verified(max_uid):
            return {
                "notification": "Ожидает проверки",
                "text": "Раздел «Мои проекты» откроется после подтверждения профиля администратором.",
                "format": "markdown",
                "attachments": visit_card.client_pre_erp_pending_keyboard(),
            }
        if not is_max_visit_client_verified(max_uid):
            return {
                "notification": "Нужна регистрация",
                "text": "Сначала пройдите регистрацию заказчика (юрлицо).",
                "format": "markdown",
                "attachments": visit_card.main_menu_keyboard(),
            }
        return {
            "notification": " ",
            "text": (
                "*Мои проекты*\n\n"
                "Раздел подключается к учёту в панели (promostaff-bot). "
                "Скоро здесь будет список проектов."
            ),
            "format": "markdown",
            "attachments": visit_card.client_registered_main_menu_keyboard(),
        }

    if payload == "client_reg_orders":
        if is_max_visit_client_registered(max_uid) and not is_max_visit_client_verified(max_uid):
            return {
                "notification": "Ожидает проверки",
                "text": (
                    "Раздел «История заказов» и статусы расчётов доступны "
                    "после проверки профиля администратором."
                ),
                "format": "markdown",
                "attachments": visit_card.client_pre_erp_pending_keyboard(),
            }
        if not is_max_visit_client_verified(max_uid):
            return {
                "notification": "Нужна регистрация",
                "text": "Сначала пройдите регистрацию заказчика (юрлицо).",
                "format": "markdown",
                "attachments": visit_card.main_menu_keyboard(),
            }
        rows = list_agency_visit_orders_for_user(max_uid, limit=25)
        if not rows:
            body = (
                "*История заказов*\n\n"
                "Пока нет заявок. Оформите расчёт через «Заказать расчёт»."
            )
        else:
            lines = ["*История заказов*\n"]
            kind_labels = {"cp_request": "КП", "quick_estimate": "Срочный расчёт"}
            for r in rows:
                p = r.get("payload") or {}
                kind = kind_labels.get((r.get("order_kind") or "").strip(), "Заявка")
                ref = (r.get("public_ref") or "").strip() or f"MX-{r.get('crm_id', '—')}"
                et = (p.get("event_type") or "").strip() or "—"
                city = (p.get("city") or "").strip() or "—"
                lines.append(f"• *{ref}* — {kind}\n  _{et}, {city}_\n")
            body = "\n".join(lines)
        return {
            "notification": " ",
            "text": body,
            "format": "markdown",
            "attachments": visit_card.client_registered_main_menu_keyboard(),
        }

    if payload == "client_reg_settings":
        if not is_max_visit_client_verified(max_uid):
            return {
                "notification": "Нужна регистрация",
                "text": "Сначала пройдите регистрацию заказчика.",
                "format": "markdown",
                "attachments": visit_card.main_menu_keyboard(),
            }
        return {
            "notification": " ",
            "text": "*Настройки*\n\nЗаглушка: уведомления и профиль — в следующих версиях.",
            "format": "markdown",
            "attachments": visit_card.client_registered_main_menu_keyboard(),
        }

    if payload == "client_reg_web":
        if not is_max_visit_client_verified(max_uid):
            return {
                "notification": "Нужна регистрация",
                "text": "Сначала пройдите регистрацию заказчика.",
                "format": "markdown",
                "attachments": visit_card.main_menu_keyboard(),
            }
        return {
            "notification": " ",
            "text": (
                "*Веб-панель*\n\n"
                "Вход будет доступен по ссылке из настроек (SSO / T-Банк — по готовности)."
            ),
            "format": "markdown",
            "attachments": visit_card.client_registered_main_menu_keyboard(),
        }

    worker_texts = {
        "worker_reg_profile": "*Мои данные*\n\nРедактирование анкеты — в следующей итерации (ТЗ Pro).",
        "worker_reg_shifts": "*Мои смены*\n\nСписок смен — после связи с учётом в панели.",
        "worker_reg_payments": "*Мои выплаты*\n\nВыплаты и T-Банк — по готовности данных.",
        "worker_reg_beacon": "*Маяк*\n\nСрочный поиск: окно активности и уведомления — в разработке.",
    }
    if payload in worker_texts:
        if not is_max_visit_worker_verified(max_uid):
            return {
                "notification": "Сначала регистрация и верификация",
                "text": (
                    "Сначала пройдите регистрацию исполнителя и дождитесь подтверждения заявки администратором."
                ),
                "format": "markdown",
                "attachments": visit_card.main_menu_keyboard(),
            }
        return {
            "notification": " ",
            "text": worker_texts[payload],
            "format": "markdown",
            "attachments": visit_card.worker_registered_main_menu_keyboard(),
        }

    return None


async def process_callback(
    max_uid: int, payload: str, sender: dict[str, Any] | None
) -> dict[str, Any] | None:
    payload = _norm_cb_payload(payload)
    who = _sender_label(sender)
    s = SESSIONS.get(max_uid)
    _reg_payloads = frozenset(
        {
            "client_reg_projects",
            "client_reg_orders",
            "client_reg_settings",
            "client_reg_web",
            "worker_reg_profile",
            "worker_reg_shifts",
            "worker_reg_payments",
            "worker_reg_beacon",
        }
    )
    if payload in _reg_payloads:
        return registered_menu_static_reply(max_uid, payload)
    if payload == "clrf:ack":
        import visit_clarification_flows as vcf

        return vcf.process_clarification_ack(max_uid)
    if payload == "clrf:start":
        import visit_clarification_flows as vcf

        s_cl = {"flow": "clarification", "step": "idle", "data": {}}
        SESSIONS[max_uid] = s_cl
        return vcf.start_clarification_input(max_uid, s_cl)
    if payload == "client_quote_listing":
        return start_listing_order(max_uid)
    if payload == "client_quote_quick":
        return start_client_quote(max_uid, preset="quick")
    if payload == "client_quote_cp":
        return start_client_quote(max_uid, preset="cp")
    if not s:
        return None
    flow = s.get("flow")
    step = s.get("step")
    data = s.setdefault("data", {})
    join_tax = _join_tax_callbacks(s, payload)
    if join_tax is not None:
        return join_tax

    if flow == "join" and step == "tbank_cabinet" and payload == "join_tbank_proceed":
        s["step"] = "tbank_register_confirm"
        return {
            "notification": "Подтверждение",
            "text": visit_card.tbank_register_confirm_prompt_md(),
            "format": "markdown",
            "attachments": visit_card.tbank_register_confirm_keyboard(),
        }

    if flow == "join" and step == "tbank_register_confirm":
        if payload == "join_tbank_reg_yes":
            return {
                "notification": "Подтверждение записано",
                **_join_begin_identity_chain(s),
            }
        if payload == "join_tbank_reg_no":
            kb = visit_card.tbank_register_blocked_keyboard() or visit_card.tbank_register_confirm_keyboard()
            return {
                "notification": "Сначала ЛК Т-Банка",
                "text": visit_card.tbank_register_must_complete_md(),
                "format": "markdown",
                "attachments": kb,
            }
        if payload == "join_tbank_reg_retry":
            s["step"] = "tbank_register_confirm"
            return {
                "notification": " ",
                "text": visit_card.tbank_register_confirm_prompt_md(),
                "format": "markdown",
                "attachments": visit_card.tbank_register_confirm_keyboard(),
            }

    if flow == "join" and step in ("tbank_cabinet", "tbank_register_confirm"):
        return {
            "notification": "Используйте кнопки",
            "text": "Используйте кнопки под сообщением бота.",
            "format": "markdown",
            "attachments": visit_card.tbank_register_confirm_keyboard(),
        }

    if flow == "client_visit" and step == "consent" and payload == "consent_client_visit_accept":
        s["step"] = "company_name"
        return {
            "notification": "Согласие принято ✅",
            "text": (
                "🏢 *Регистрация заказчика*\n\n"
                "Введите *полное* юридическое название организации (как в учредительных документах):"
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
        clear_session(max_uid)
        return {
            "notification": "Принято!",
            "text": (
                "✅ *Регистрация принята.*\n\n"
                "Данные проверяет администратор. После подтверждения откроются расчёт, "
                "запрос КП и раздел «История заказов».\n\n"
                "Пока можете написать менеджеру."
            ),
            "format": "markdown",
            "attachments": visit_card.client_pre_erp_pending_keyboard(),
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
        s["step"] = "order_mode"
        return {
            "notification": "Согласие принято ✅",
            "text": (
                "*Заказ расчёта стоимости*\n\n"
                "*Срочный расчёт* — оценка по одной типичной смене прямо в боте.\n"
                "*Коммерческое предложение* — менеджер подготовит КП по вашим вводным.\n\n"
                "Выберите вариант:"
            ),
            "format": "markdown",
            "attachments": visit_card.order_mode_keyboard(),
        }

    if flow == "order" and payload == "cp_flow_back":
        step = s.get("step")
        if step == "cp_event_type":
            s["step"] = "order_mode"
            return {
                "notification": "Сценарий",
                "text": "*Заказ расчёта стоимости*\n\nВыберите вариант:",
                "format": "markdown",
                "attachments": visit_card.order_mode_keyboard(),
            }
        if step == "cp_city":
            s["step"] = "cp_event_type"
            return {
                "notification": "Назад",
                "text": (
                    "*Запрос коммерческого предложения*\n\n"
                    "Опишите *тип мероприятия* (выставка, промо, корпоратив и т.д.).\n\n"
                    "_Образец:_ `Корпоратив, 200 гостей, Москва-Сити`\n\n"
                ),
                "format": "markdown",
                "attachments": visit_card.cp_step_keyboard(),
            }
        if step == "cp_dates":
            s["step"] = "cp_city"
            return {
                "notification": "Назад",
                "text": "Укажите город проведения мероприятия.\n\n_Образец:_ `Москва`",
                "format": "markdown",
                "attachments": visit_card.cp_step_keyboard(),
            }
        if step == "cp_brief_wait":
            s["step"] = "cp_dates"
            return {
                "notification": "Назад",
                "text": (
                    "Укажите даты мероприятия или период.\n\n"
                    "_Образец:_ `15.06.2026` или `12–14 июня 2026`\n\n"
                ),
                "format": "markdown",
                "attachments": visit_card.cp_step_keyboard(),
            }
        if step == "cp_brief_text":
            s["step"] = "cp_brief_wait"
            return {
                "notification": "Назад",
                "text": "У вас есть готовый бриф или техническое задание?",
                "format": "markdown",
                "attachments": visit_card.cp_brief_keyboard(),
            }
        if step == "cp_channel_pick":
            s["step"] = "cp_brief_wait"
            return {
                "notification": "Назад",
                "text": "У вас есть готовый бриф или техническое задание?",
                "format": "markdown",
                "attachments": visit_card.cp_brief_keyboard(),
            }
        if step == "cp_call_time":
            s["step"] = "cp_channel_pick"
            return {
                "notification": "Назад",
                "text": "Как удобнее связаться по КП?",
                "format": "markdown",
                "attachments": visit_card.cp_channel_keyboard(),
            }
        return None

    if flow == "order" and payload == "order_flow_back":
        step = s.get("step")
        if step == "event_type":
            s["step"] = "order_mode"
            return {
                "notification": "Назад",
                "text": "*Заказ расчёта стоимости*\n\nВыберите вариант:",
                "format": "markdown",
                "attachments": visit_card.order_mode_keyboard(),
            }
        if step == "city":
            s["step"] = "event_type"
            return {
                "notification": "Назад",
                "text": (
                    "*Срочный расчёт*\n\n"
                    "Выберите быстрый сценарий или введите тип проекта вручную.\n\n"
                ),
                "format": "markdown",
                "attachments": visit_card.order_quickstart_keyboard(),
            }
        if step == "event_date":
            s["step"] = "city"
            return {
                "notification": "Назад",
                "text": "Укажите город проведения мероприятия.\n\n_Образец:_ `Москва`",
                "format": "markdown",
                "attachments": visit_card.order_flow_back_keyboard(),
            }
        if step == "shift_time":
            s["step"] = "event_date"
            return {
                "notification": "Назад",
                "text": (
                    "Укажите дату мероприятия или период (можно несколько дней).\n\n"
                    "_Образец:_ `15.06.2026` или `12–14 июня 2026`\n\n"
                ),
                "format": "markdown",
                "attachments": visit_card.order_flow_back_keyboard(),
            }
        return None

    if flow == "order" and step == "order_mode" and payload in (
        "order_mode_quick",
        "order_mode_cp",
        "order_mode_listing",
    ):
        blocked = _gate_client_quote_access(max_uid)
        if blocked:
            clear_session(max_uid)
            return blocked

    if flow == "order" and step == "order_mode" and payload == "order_mode_quick":
        data.pop("order_kind", None)
        for k in (
            "event_type",
            "city",
            "event_date",
            "cp_brief_has",
            "cp_brief_note",
            "cp_brief_file_name",
            "cp_brief_max_url",
            "cp_contact_channel",
            "cp_call_time",
        ):
            data.pop(k, None)
        s["step"] = "event_type"
        return {
            "notification": "Срочный расчёт",
            "text": (
                "*Срочный расчёт*\n\n"
                "Выберите быстрый сценарий или введите тип проекта вручную.\n\n"
            ),
            "format": "markdown",
            "attachments": visit_card.order_quickstart_keyboard(),
        }

    if flow == "order" and step == "order_mode" and payload == "order_mode_cp":
        data["order_kind"] = "cp_request"
        for k in (
            "event_type",
            "city",
            "event_date",
            "cp_brief_has",
            "cp_brief_note",
            "cp_brief_file_name",
            "cp_brief_max_url",
            "cp_contact_channel",
            "cp_call_time",
        ):
            data.pop(k, None)
        s["step"] = "cp_event_type"
        return {
            "notification": "Запрос КП",
            "text": (
                "*Запрос коммерческого предложения*\n\n"
                "Опишите *тип мероприятия* (выставка, промо, корпоратив и т.д.).\n\n"
                "_Образец:_ `Корпоратив, 200 гостей, Москва-Сити`\n\n"
            ),
            "format": "markdown",
            "attachments": visit_card.cp_step_keyboard(),
        }

    if flow == "order" and step == "order_mode" and payload == "order_mode_listing":
        return start_listing_order(max_uid)

    if flow == "order" and step == "contact_channel_pick":
        if payload == "contact_ch_call":
            data["contact_channel"] = "call"
            s["step"] = "call_time"
            return {
                "notification": "Звонок",
                "text": (
                    "Когда удобно принять звонок менеджера?\n\n"
                    "_Образец:_ `будни 10:00–18:00`"
                ),
                "format": "markdown",
                "attachments": visit_card.order_flow_back_keyboard(),
            }
        if payload == "contact_ch_max":
            data["contact_channel"] = "max_chat"
            s["step"] = "listing_confirm"
            return {
                "notification": "MAX",
                "text": _listing_preview_text(data),
                "format": "markdown",
                "attachments": visit_card.listing_confirm_keyboard(),
            }
        if payload == "contact_ch_mail":
            data["contact_channel"] = "email"
            s["step"] = "listing_confirm"
            return {
                "notification": "Email",
                "text": _listing_preview_text(data),
                "format": "markdown",
                "attachments": visit_card.listing_confirm_keyboard(),
            }

    if flow == "order" and step == "listing_confirm" and payload == "confirm_listing_order":
        blocked = _gate_client_quote_access(max_uid)
        if blocked:
            clear_session(max_uid)
            return blocked
        if not data.get("order_consent_accepted"):
            return {
                "notification": "Сначала согласие на ПДн",
                "text": _consent_gate_text("размещение объявления"),
                "format": "markdown",
                "attachments": visit_card.consent_gate_keyboard("order"),
            }
        role = (data.get("listing_role") or "").strip()
        if len(role) < 2 or len((data.get("listing_description") or "").strip()) < 10:
            return {
                "notification": "Проверьте поля",
                "text": "Заполните роль, описание и остальные поля объявления.",
                "format": "markdown",
                "attachments": visit_card.listing_confirm_keyboard(),
            }
        if not _order_contact_ready(data):
            return _advance_order_contact_step(max_uid, s, notification="Нужны контакты")
        oid = _new_id()
        to_save = dict(data)
        to_save["order_kind"] = "vacancy_listing"
        to_save["listing_publication_fee_rub"] = int(
            to_save.get("listing_publication_fee_rub") or LISTING_PUBLICATION_FEE_RUB
        )
        if role:
            to_save["event_type"] = f"Объявление: {role[:120]}"
        username = (sender or {}).get("username") if isinstance(sender, dict) else ""
        public_ref = "—"
        try:
            _, public_ref = save_visit_order_payload(max_uid, str(username or ""), to_save)
        except Exception:
            logger.exception("save_visit_order_payload listing")
        _schedule_notify(f"Новая заявка на объявление #{oid}", _format_listing_plain(to_save, oid, who))
        ref_show = (
            public_ref if public_ref not in (None, "OFFLINE", "—") else f"внутр. #{oid}"
        )
        funnel_touch_complete(max_uid)
        clear_session(max_uid)
        return {
            "notification": "✅ Заявка принята",
            "text": (
                f"*Заявка на объявление принята.* Номер: `{ref_show}`\n\n"
                "Менеджер выставит счёт; публикация в ленте — после оплаты.\n\n"
                "*Меню заказчика* — ниже."
            ),
            "format": "markdown",
            "attachments": visit_card.client_registered_main_menu_keyboard(),
        }

    if flow == "order" and step == "listing_confirm" and payload == "edit_listing_order":
        fee = int(data.get("listing_publication_fee_rub") or LISTING_PUBLICATION_FEE_RUB)
        s["step"] = "listing_position"
        data.pop("listing_role", None)
        data.pop("listing_description", None)
        data.pop("city", None)
        data.pop("event_date", None)
        data["listing_publication_fee_rub"] = fee
        fee_md = f"{fee:,}".replace(",", " ")
        return {
            "notification": "Заполняем заново",
            "text": (
                f"*Разместить объявление*\n\n"
                f"Ориентир тарифа: *{fee_md}* ₽.\n\n"
                "Шаг 1 из 4. Укажите *роль или задачу*.\n\n"
                "_Образец:_ `Промоутеры на дегустацию в ТЦ`"
            ),
            "format": "markdown",
            "attachments": visit_card.order_flow_back_keyboard(),
        }

    if flow == "question" and step == "consent" and payload == "consent_question_accept":
        data["question_consent_accepted"] = True
        s["step"] = "text"
        return {
            "notification": "Согласие принято ✅",
            "text": (
                "*Сообщение менеджеру*\n\n"
                "Напишите вопрос одним сообщением — мы ответим в рабочее время.\n\n"
            ),
            "format": "markdown",
            "attachments": visit_card.back_to_main_keyboard(),
        }

    if flow == "join" and step == "terms_accept" and payload == "join_terms_agree":
        s["step"] = "portfolio_menu"
        return {"notification": "Принято ✅", **_join_prompt_portfolio_menu()}

    if flow == "join" and step == "portfolio_menu" and payload == "join_portfolio_none":
        data["portfolio_mode"] = "none"
        data["portfolio_url"] = ""
        data["portfolio_pdf_file_id"] = ""
        s["step"] = "selfie"
        return {"notification": " ", **_join_prompt_selfie()}

    if flow == "join" and step == "portfolio_menu" and payload == "join_portfolio_pdf":
        data["portfolio_mode"] = "pdf"
        data["portfolio_url"] = ""
        data["portfolio_pdf_file_id"] = ""
        s["step"] = "portfolio_pdf"
        return {
            "notification": "PDF",
            "text": (
                "📄 *ПОРТФОЛИО (PDF)*\n\n"
                "Пришлите файл **одним документом** (скрепка → Файл), формат **PDF**."
            ),
            "format": "markdown",
            "attachments": visit_card.back_to_main_keyboard(),
        }

    if flow == "join" and step == "portfolio_menu" and payload == "join_portfolio_url":
        data["portfolio_mode"] = "url"
        data["portfolio_pdf_file_id"] = ""
        s["step"] = "portfolio_url"
        return {
            "notification": "Ссылка",
            "text": "🔗 *ПОРТФОЛИО (ССЫЛКА)*\n\nОдним сообщением пришлите ссылку, начинающуюся с **https://**.",
            "format": "markdown",
            "attachments": visit_card.back_to_main_keyboard(),
        }

    if flow == "join" and step == "work_metro" and payload == "join_metro_skip":
        data["metro_station"] = ""
        return _join_go_to_review(s, data)

    if flow == "join" and step == "terms_accept" and payload == "join_terms_decline":
        clear_session(max_uid)
        return {
            "notification": "Регистрация не завершена",
            "text": (
                "Без согласия с условиями регистрацию завершить нельзя. Вы в меню визитки."
            ),
            "format": "markdown",
            "attachments": visit_card.main_menu_keyboard(),
        }

    if flow == "join" and step == "consent" and payload == "consent_join_accept":
        data["join_consent_accepted"] = True
        if data.get("join_entry") == "vacancy" and data.get("position"):
            s["step"] = "full_name"
            return {
                "notification": "Согласие принято ✅",
                "text": f"Должность: *{data.get('position')}*\n\n{_basic_info_intro()}",
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        s["step"] = "anketa_invite"
        return {
            "notification": "Согласие принято ✅",
            "text": (
                "Для получения предложений о работе заполните анкету.\n\n"
                "Чем подробнее вы заполните профиль, тем точнее будут предложения."
            ),
            "format": "markdown",
            "attachments": visit_card.join_anketa_invite_keyboard(),
        }

    if flow == "join" and step == "anketa_invite" and payload == "join_proceed_anketa":
        if not data.get("join_consent_accepted"):
            return {
                "notification": "Сначала подтвердите согласие.",
                "text": _consent_gate_text("отклик в команду"),
                "format": "markdown",
                "attachments": visit_card.consent_gate_keyboard("join"),
            }
        s["step"] = "profession_category"
        return {
            "notification": "Заполняем анкету…",
            "text": "*ВЫБОР ПРОФЕССИИ*\n\nВыберите категорию 👇",
            "format": "markdown",
            "attachments": visit_card.profession_categories_keyboard(),
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
                "_После выбора нажмите «Готово»._\n\n👇"
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
                ),
                "format": "markdown",
                "attachments": visit_card.order_flow_back_keyboard(),
            }
        preset = presets.get(payload)
        if not preset:
            return None
        data["event_type"] = preset
        s["step"] = "city"
        return {
            "notification": "Сценарий применён ✅",
            "text": "Укажите город проведения мероприятия.\n\n_Образец:_ `Москва`",
            "format": "markdown",
            "attachments": visit_card.order_flow_back_keyboard(),
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
            return _advance_order_contact_step(
                max_uid, s, notification="📞 Дальше — контакт для связи."
            )
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
        out = _advance_order_contact_step(
            max_uid,
            s,
            notification="✅ Супервайзер в оценке (900 ₽/ч днём, ночь +15%). Дальше — контакты.",
        )
        prev = out.get("text") or ""
        out["text"] = f"В предварительный расчёт добавлено: *{rec}* {sv_word}.\n\n{prev}"
        return out

    if flow == "order" and step == "supervisor_offer" and payload == "sv_skip":
        data["supervisor_count"] = 0
        out = _advance_order_contact_step(
            max_uid,
            s,
            notification="Ок. По супервайзеру и составу можно обсудить с менеджером после заявки.",
        )
        prev = out.get("text") or ""
        out["text"] = (
            "Супервайзер в расчёт не включён — при необходимости менеджер предложит варианты.\n\n"
            f"{prev}"
        )
        return out

    if flow == "order" and step == "cp_brief_wait" and payload == "cp_brief_yes":
        s["step"] = "cp_brief_text"
        return {
            "notification": "Опишите бриф",
            "text": (
                "*Бриф / ТЗ*\n\n"
                "Кратко опишите задачу или ключевые требования *текстом* "
                "и/или пришлите *фото* или *документ* (Word, Excel, PDF и др.) — "
                "подпись к вложению необязательна.\n\n"
            ),
            "format": "markdown",
            "attachments": visit_card.cp_step_keyboard(),
        }

    if flow == "order" and step == "cp_brief_wait" and payload == "cp_brief_no":
        data["cp_brief_has"] = False
        data["cp_brief_note"] = ""
        data.pop("cp_brief_max_url", None)
        data.pop("cp_brief_file_name", None)
        s["step"] = "cp_channel_pick"
        return {
            "notification": "Дальше — способ связи",
            "text": "Как удобнее связаться по КП?",
            "format": "markdown",
            "attachments": visit_card.cp_channel_keyboard(),
        }

    if flow == "order" and step == "cp_channel_pick" and payload == "cp_ch_call":
        data["cp_contact_channel"] = "call"
        s["step"] = "cp_call_time"
        return {
            "notification": "Звонок",
            "text": "Когда удобно принять звонок менеджера?\n\n_Образец:_ `будни 10:00–18:00`",
            "format": "markdown",
            "attachments": visit_card.cp_step_keyboard(),
        }

    if flow == "order" and step == "cp_channel_pick" and payload == "cp_ch_msg":
        data["cp_contact_channel"] = "max_chat"
        _hydrate_order_contact_from_visit(max_uid, data)
        s["step"] = "cp_confirm"
        return {
            "notification": "Связь в MAX",
            "text": _cp_preview_text(data),
            "format": "markdown",
            "attachments": visit_card.cp_confirm_keyboard(),
        }

    if flow == "order" and step == "cp_channel_pick" and payload == "cp_ch_mail":
        data["cp_contact_channel"] = "email"
        _hydrate_order_contact_from_visit(max_uid, data)
        s["step"] = "cp_confirm"
        return {
            "notification": "Email",
            "text": _cp_preview_text(data),
            "format": "markdown",
            "attachments": visit_card.cp_confirm_keyboard(),
        }

    if flow == "order" and step == "cp_confirm" and payload == "confirm_cp_order":
        blocked = _gate_client_quote_access(max_uid)
        if blocked:
            clear_session(max_uid)
            return blocked
        if not data.get("order_consent_accepted"):
            return {
                "notification": "Сначала подтвердите согласие на обработку ПДн.",
                "text": _consent_gate_text("заказ расчёта"),
                "format": "markdown",
                "attachments": visit_card.consent_gate_keyboard("order"),
            }
        oid = _new_id()
        to_save = dict(data)
        to_save["order_kind"] = "cp_request"
        plain = _format_cp_plain(to_save, oid, who)
        username = (sender or {}).get("username") if isinstance(sender, dict) else ""
        public_ref = "—"
        try:
            _, public_ref = save_visit_order_payload(max_uid, str(username or ""), to_save)
        except Exception:
            logger.exception("save_visit_order_payload cp")
        _schedule_notify(f"Новая заявка на КП #{oid}", plain)
        ref_show = (
            public_ref if public_ref not in (None, "OFFLINE", "—") else f"внутр. #{oid}"
        )
        funnel_touch_complete(max_uid)
        clear_session(max_uid)
        return {
            "notification": "✅ Заявка на КП у команды.",
            "text": (
                f"*Заявка на КП принята.* Номер: `{ref_show}`\n\n"
                "Менеджер подготовит предложение и свяжется с вами.\n\n"
                "*Меню заказчика* — ниже.",
            ),
            "format": "markdown",
            "attachments": visit_card.client_registered_main_menu_keyboard(),
        }

    if flow == "order" and step == "cp_confirm" and payload == "edit_cp_order":
        data.pop("order_kind", None)
        for k in (
            "event_type",
            "city",
            "event_date",
            "cp_brief_has",
            "cp_brief_note",
            "cp_contact_channel",
            "cp_call_time",
        ):
            data.pop(k, None)
        s["step"] = "order_mode"
        return {
            "notification": "Заполняем заново",
            "text": (
                "*Заказ расчёта стоимости*\n\n"
                "Выберите вариант:"
            ),
            "format": "markdown",
            "attachments": visit_card.order_mode_keyboard(),
        }

    if flow == "order" and step == "confirm" and payload == "confirm_order":
        blocked = _gate_client_quote_access(max_uid)
        if blocked:
            clear_session(max_uid)
            return blocked
        if not data.get("order_consent_accepted"):
            return {
                "notification": "Подтвердите согласие на обработку персональных данных перед отправкой заявки.",
                "text": (
                    "Перед отправкой заявки подтвердите согласие кнопкой ниже.\n\n"
                    f"Политика: {PRIVACY_POLICY_URL}\n\n"
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
        username = (sender or {}).get("username") if isinstance(sender, dict) else ""
        try:
            save_visit_order(max_uid, str(username or ""), json.dumps(to_save, ensure_ascii=False))
        except Exception:
            logger.exception("save_visit_order")
        _schedule_notify(f"Новая заявка на расчёт #{oid}", plain)
        funnel_touch_complete(max_uid)
        clear_session(max_uid)
        return {
            "notification": "✅ Заявка у команды. Менеджер свяжется для уточнения деталей и точной сметы.",
            "text": (
                f"*Заявка #{oid} принята.*\n\n"
                "Спасибо! Менеджер свяжется с вами в ближайшее время.\n\n"
            ),
            "format": "markdown",
            "attachments": visit_card.main_menu_keyboard(),
        }

    if flow == "order" and step == "confirm" and payload == "edit_order":
        clear_session(max_uid)
        msg = start_order(max_uid, announce_order_consent=False)
        msg["notification"] = "Заполняем заявку заново…"
        return msg

    if flow == "join" and step == "profession_category":
        low = payload.lower()
        if low in ("main_menu", "back", "back_to_main"):
            return None
        if low == "prof_back":
            return {
                "notification": " ",
                "text": "*ВЫБОР ПРОФЕССИИ*\n\nВыберите категорию 👇",
                "format": "markdown",
                "attachments": visit_card.profession_categories_keyboard(),
            }
        if low.startswith("prof_cat:"):
            cat_s = payload.split(":", 1)[-1].strip().lower()
            try:
                cat = ProfessionCategory(cat_s)
            except ValueError:
                logger.warning(
                    "join prof_cat invalid max_uid=%s payload=%r cat_s=%r",
                    max_uid,
                    payload,
                    cat_s,
                )
                return {
                    "notification": "Выберите категорию кнопкой",
                    "text": "*ВЫБОР ПРОФЕССИИ*\n\nВыберите категорию 👇",
                    "format": "markdown",
                    "attachments": visit_card.profession_categories_keyboard(),
                }
            data["profession_category"] = cat.value
            return {
                "notification": " ",
                "text": (
                    "Выберите профессию из списка ниже 👇\n\n"
                    "_Если вашей профессии нет в списке, нажмите кнопку «Добавить новую профессию» "
                    "и введите её название._"
                ),
                "format": "markdown",
                "attachments": visit_card.profession_list_keyboard(cat),
            }
        if low.startswith("prof_pick:"):
            slug = payload.split(":", 1)[-1].strip().lower()
            title = PROFESSION_SLUG_TO_TITLE.get(slug)
            if not title:
                logger.warning("join prof_pick unknown slug max_uid=%s payload=%r", max_uid, payload)
                return {
                    "notification": "Выберите профессию из списка",
                    "text": "*ВЫБОР ПРОФЕССИИ*\n\nВыберите профессию кнопкой ниже.",
                    "format": "markdown",
                    "attachments": visit_card.profession_categories_keyboard(),
                }
            data["position"] = title
            s["step"] = "full_name"
            return {
                "notification": f"Профессия: {title}",
                "text": _basic_info_intro(),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if low.startswith("prof_custom:"):
            cat_s = payload.split(":", 1)[-1].strip().lower()
            try:
                ProfessionCategory(cat_s)
            except ValueError:
                logger.warning(
                    "join prof_custom bad category max_uid=%s payload=%r", max_uid, payload
                )
                return {
                    "notification": "Выберите категорию",
                    "text": "*ВЫБОР ПРОФЕССИИ*\n\nВыберите категорию 👇",
                    "format": "markdown",
                    "attachments": visit_card.profession_categories_keyboard(),
                }
            data["profession_category"] = cat_s
            s["step"] = "profession_custom"
            return {
                "notification": " ",
                "text": "Введите название профессии одним сообщением (например: *Бариста*).",
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        logger.warning(
            "join profession_category unhandled max_uid=%s payload=%r keys_session=%s",
            max_uid,
            payload,
            list(s.keys()) if s else None,
        )
        return {
            "notification": " ",
            "text": "*ВЫБОР ПРОФЕССИИ*\n\nВыберите категорию или профессию кнопками ниже.",
            "format": "markdown",
            "attachments": visit_card.profession_categories_keyboard(),
        }

    if flow == "join" and step == "experience_pick" and payload in ("exp_lt1", "exp_1_3", "exp_gt3"):
        label, stars = visit_join_validators.experience_stars_from_choice(payload)
        if not label:
            return None
        data["experience_years"] = label
        data["experience_base_stars"] = stars
        data["experience_tag"] = visit_join_validators.experience_tag_from_stars(stars)
        s["step"] = "experience_desc"
        return {
            "notification": label,
            "text": (
                "*Кратко опишите ваш опыт:*\n\n"
                "_Где работали? Какие задачи выполняли?_\n\n"
                "💡 _Чем подробнее описание, тем выше шанс получить предложения._\n\n"
                "_Пример: «Промо в ТРЦ 2 года, выкладка, общение с гостями, отчётность фото»._"
            ),
            "format": "markdown",
            "attachments": visit_card.back_to_main_keyboard(),
        }

    if flow == "join" and step == "param_gender" and payload in ("gender_m", "gender_f"):
        data["gender"] = "Мужской" if payload == "gender_m" else "Женский"
        s["step"] = "param_clothing"
        return {
            "notification": data["gender"],
            "text": "*Укажите ваш размер одежды:*\n\n_XS, S, M, L, XL, XXL_",
            "format": "markdown",
            "attachments": visit_card.clothing_size_keyboard(),
        }

    if flow == "join" and step == "param_clothing" and payload.startswith("size_"):
        size = payload.replace("size_", "", 1)
        data["clothing_size"] = size
        s["step"] = "param_shoe"
        return {
            "notification": size,
            "text": (
                "👟 *Укажите ваш размер обуви:*\n\n"
                "_Диапазон 35–48. 0 = пропустить._"
            ),
            "format": "markdown",
            "attachments": visit_card.back_to_main_keyboard(),
        }

    if flow == "join" and step == "uniform_choice":
        if payload == "uniform_info":
            return {
                "notification": " ",
                "text": visit_card.text_uniform_requirements(),
                "format": "markdown",
                "attachments": visit_card.uniform_after_info_keyboard(),
            }
        if payload in ("uniform_own_yes", "uniform_own_no"):
            own = payload == "uniform_own_yes"
            data["uniform_has_own"] = own
            data["uniform_choice_label"] = "Своя форма" if own else "Нужна от работодателя"
            s["step"] = "medbook_has"
            return {
                "notification": " ",
                "text": (
                    "*🏥 ДОКУМЕНТЫ*\n\n"
                    "_Для работы с продуктами питания, детьми и в детских учреждениях может требоваться "
                    "медицинская книжка._\n\n"
                    "*Медицинская книжка:*"
                ),
                "format": "markdown",
                "attachments": visit_card.medbook_has_keyboard(),
            }

    if flow == "join" and step == "medbook_has":
        if payload == "medbook_yes":
            data["medbook_has"] = True
            s["step"] = "medbook_number"
            return {
                "notification": " ",
                "text": "Укажите *номер медицинской книжки* текстом.",
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if payload == "medbook_no":
            data["medbook_has"] = False
            data["medbook_label"] = "Нет"
            s["step"] = "trips"
            return {
                "notification": " ",
                "text": "*Готовы ли вы к командировкам?*",
                "format": "markdown",
                "attachments": visit_card.trips_keyboard(),
            }

    if flow == "join" and step == "trips" and payload in ("trips_yes", "trips_no"):
        ok = payload == "trips_yes"
        data["trips_ok"] = ok
        data["trips_label"] = "Готов(а)" if ok else "Не готов(а)"
        s["step"] = "skills"
        return {
            "notification": " ",
            "text": (
                "🔧 *Укажите ваши ключевые навыки одним сообщением.*\n\n"
                "_Например: водительские права кат. B, английский B1, работа с грузами._\n\n"
                "Чтобы пропустить, отправьте `0`."
            ),
            "format": "markdown",
            "attachments": visit_card.back_to_main_keyboard(),
        }

    if flow == "join" and step == "review_submit" and payload == "join_review_edit":
        jc = data.get("join_consent_accepted")
        je = data.get("join_entry") or "profile"
        pos = data.get("position") if je == "vacancy" else None
        new_data: dict[str, Any] = {"join_consent_accepted": jc, "join_entry": je}
        if je == "vacancy" and pos:
            new_data["position"] = pos
        s["data"] = new_data
        if je == "vacancy" and pos:
            s["step"] = "full_name"
            return {
                "notification": "Заполняем заново…",
                "text": f"Должность: *{pos}*\n\n{_basic_info_intro()}",
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        s["step"] = "profession_category"
        return {
            "notification": "Заполняем заново…",
            "text": "*ВЫБОР ПРОФЕССИИ*\n\nВыберите категорию 👇",
            "format": "markdown",
            "attachments": visit_card.profession_categories_keyboard(),
        }

    if flow == "join" and step == "review_submit" and payload in ("join_review_ok", "submit_join_anketa"):
        rid = _new_id()
        aligned = _align_join_payload_for_pg(data)
        aligned["specialization_tags"] = _build_join_tags(aligned)
        plain = _format_join_plain(aligned, rid, who)
        username = (sender or {}).get("username") if isinstance(sender, dict) else ""
        try:
            save_visit_join(max_uid, str(username or ""), json.dumps(aligned, ensure_ascii=False))
        except Exception:
            logger.exception("save_visit_join")
        _schedule_notify(f"Новая заявка в команду #{rid}", plain)
        funnel_touch_complete(max_uid)
        clear_session(max_uid)
        return {
            "notification": "Отправлено на проверку ✅",
            "text": (
                f"*Заявка #{rid} отправлена на проверку.*\n\n"
                f"После подтверждения администратором вам откроется меню исполнителя.\n\n"
                f"Спасибо за интерес к {COMPANY_NAME}!"
            ),
            "format": "markdown",
            "attachments": visit_card.worker_pending_verification_keyboard(),
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

    if flow == "clarification" and step == "waiting_input":
        import visit_clarification_flows as vcf

        ref = _image_ref_from_body(message_body) or ""
        return vcf.process_clarification_text(max_uid, s, text, file_ref=ref)

    if step == "consent":
        if flow == "client_visit":
            return {
                "text": "Нажмите кнопку согласия ниже или вернитесь в меню.",
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
                    "Введите *ИНН* организации (10 цифр для юрлица или 12 для ИП) — сразу после названия, "
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
                "text": "Введите *полное ФИО* контактного лица:",
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
                "text": "Укажите *вашу должность* в организации:",
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
                "text": "Отправьте номер телефона кнопкой или введите вручную в формате +7…",
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "email":
            if not validate_email(text.strip()):
                return {
                    "text": "❌ Введите корректный email. Пример: client@company.ru",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["contact_email"] = text.strip()
            s["step"] = "confirm"
            inn = (data.get("inn") or "").strip()
            preview = (
                "📋 *Проверка данных*\n\n"
                f"🏢 Организация: {data.get('company_name', '')}\n"
                f"🧾 ИНН: {inn}\n"
                f"👤 Контактное лицо: {data.get('contact_name', '')}\n"
                f"💼 Должность: {data.get('position_in_org', '')}\n"
                f"📞 Телефон: {data.get('phone', '')}\n"
                f"✉️ Email: {data.get('contact_email', '')}\n\n"
                "Всё верно?\n\n"
            )
            return {
                "text": preview,
                "format": "markdown",
                "attachments": visit_card.client_reg_confirm_keyboard(),
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
            blocked = _phone_resolve_or_none(max_uid, s, v, "client")
            if blocked:
                return blocked
            s["step"] = "email"
            return {
                "text": (
                    "Номер сохранён.\n\n"
                    "Введите *email* для связи по проекту (коммерческие письма, КП).\n\n"
                    "_Образец:_ `client@company.ru`"
                ),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "confirm":
            return {
                "text": "Используйте кнопки под сообщением: подтвердить или заполнить заново.",
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
        username = (sender or {}).get("username") if isinstance(sender, dict) else ""
        try:
            save_visit_question(max_uid, str(username or ""), text)
        except Exception:
            logger.exception("save_visit_question")
        _schedule_notify(f"Новый вопрос #{qid}", plain)
        clear_session(max_uid)
        return {
            "text": "*Сообщение отправлено.* Спасибо!",
            "format": "markdown",
            "attachments": visit_card.main_menu_keyboard(),
        }

    if flow == "order":
        if step == "order_mode":
            return {
                "text": "Выберите вариант кнопками ниже.",
                "format": "markdown",
                "attachments": visit_card.order_mode_keyboard(),
            }
        if step == "cp_event_type":
            data["event_type"] = text.strip()
            s["step"] = "cp_city"
            return {
                "text": "Укажите город проведения мероприятия.\n\n_Образец:_ `Москва`",
                "format": "markdown",
                "attachments": visit_card.cp_step_keyboard(),
            }
        if step == "cp_city":
            data["city"] = text.strip()
            s["step"] = "cp_dates"
            return {
                "text": (
                    "Укажите даты мероприятия или период.\n\n"
                    "_Образец:_ `15.06.2026` или `12–14 июня 2026`\n\n"
                ),
                "format": "markdown",
                "attachments": visit_card.cp_step_keyboard(),
            }
        if step == "cp_dates":
            data["event_date"] = text.strip()
            s["step"] = "cp_brief_wait"
            return {
                "text": "У вас есть готовый бриф или техническое задание?",
                "format": "markdown",
                "attachments": visit_card.cp_brief_keyboard(),
            }
        if step == "cp_brief_text":
            if _message_body_has_video(message_body):
                return {
                    "text": (
                        "Видео для брифа не принимаем. Пришлите *фото* или *документ* "
                        "(Word, Excel, PDF и др.) либо опишите задачу текстом."
                    ),
                    "format": "markdown",
                    "attachments": visit_card.cp_step_keyboard(),
                }
            bf = _brief_file_from_body(message_body)
            note = (text or "").strip()
            if not bf and not note:
                return {
                    "text": (
                        "Пришлите текст брифа и/или вложение: *фото* или *файл* "
                        "(Word, Excel, PDF и др.). Подпись к файлу необязательна."
                    ),
                    "format": "markdown",
                    "attachments": visit_card.cp_step_keyboard(),
                }
            data["cp_brief_has"] = True
            data.pop("cp_brief_max_url", None)
            data.pop("cp_brief_file_name", None)
            if bf:
                data["cp_brief_max_url"] = bf["url"]
                data["cp_brief_file_name"] = bf["name"]
                data["cp_brief_note"] = note or f"Вложение: {bf['name']}"
            else:
                data["cp_brief_note"] = note
            s["step"] = "cp_channel_pick"
            return {
                "text": "Как удобнее связаться по КП?",
                "format": "markdown",
                "attachments": visit_card.cp_channel_keyboard(),
            }
        if step == "cp_call_time":
            data["cp_call_time"] = text.strip()
            _hydrate_order_contact_from_visit(max_uid, data)
            s["step"] = "cp_confirm"
            return {
                "text": _cp_preview_text(data),
                "format": "markdown",
                "attachments": visit_card.cp_confirm_keyboard(),
            }
        if step == "cp_confirm":
            return {
                "text": "Используйте кнопки под сообщением.",
                "format": "markdown",
                "attachments": visit_card.cp_confirm_keyboard(),
            }
        if step == "cp_brief_wait":
            return {
                "text": "Выберите «Да» или «Нет» кнопками ниже.",
                "format": "markdown",
                "attachments": visit_card.cp_brief_keyboard(),
            }
        if step == "cp_channel_pick":
            return {
                "text": "Выберите способ связи кнопками ниже.",
                "format": "markdown",
                "attachments": visit_card.cp_channel_keyboard(),
            }
        if step == "event_type":
            data["event_type"] = text.strip()
            s["step"] = "city"
            return {
                "text": "Укажите город проведения мероприятия.\n\n_Образец:_ `Москва`",
                "format": "markdown",
                "attachments": visit_card.order_flow_back_keyboard(),
            }
        if step == "city":
            data["city"] = text.strip()
            s["step"] = "event_date"
            return {
                "text": (
                    "Укажите дату мероприятия или период (можно несколько дней).\n\n"
                    "_Образец:_ `15.06.2026` или `12–14 июня 2026`\n\n"
                ),
                "format": "markdown",
                "attachments": visit_card.order_flow_back_keyboard(),
            }
        if step == "event_date":
            data["event_date"] = text.strip()
            s["step"] = "shift_time"
            return {
                "text": "*Время смены*\n\n" + SHIFT_STEP_TEXT,
                "format": "markdown",
                "attachments": visit_card.order_flow_back_keyboard(),
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
                    "attachments": visit_card.order_flow_back_keyboard(),
                }
            data["shift_time"] = raw
            s["step"] = "staff_pick"
            s["temp_staff"] = {}
            return {
                "text": (
                    "Выберите категории персонала и количество (нажимайте для увеличения).\n\n"
                    "_После выбора нажмите «Готово»._\n\n👇"
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
            return _advance_order_contact_step(max_uid, s)
        if step == "contact_name":
            if not validate_full_name(text):
                return {
                    "text": "Введите полное ФИО (минимум 2 слова, буквы и дефис). Пример: Иванов Иван Иванович",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["contact_name"] = text.strip()
            return _advance_order_contact_step(max_uid, s)
        if step == "contact_email":
            if not validate_email(text.strip()):
                return {
                    "text": "Некорректный email. Пример: client@company.ru",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["contact_email"] = text.strip()
            return _advance_order_contact_step(max_uid, s)
        if step == "company_name":
            company = text.strip()
            if not company or company == "—":
                return {
                    "text": "Название компании обязательно. Пример: ООО «Ромашка»",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["company_name"] = company
            return _advance_order_contact_step(max_uid, s)
        if step == "company_inn":
            raw = text.strip()
            if not validate_inn(raw):
                return {
                    "text": "ИНН обязателен и должен содержать 10 или 12 цифр. Пример: 7707083893",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["company_inn"] = re.sub(r"\D", "", raw)
            return _advance_order_contact_step(max_uid, s)
        if step == "listing_position":
            raw = text.strip()
            if len(raw) < 2:
                return {
                    "text": "Укажите роль или задачу подробнее (минимум 2 символа).",
                    "format": "markdown",
                    "attachments": visit_card.order_flow_back_keyboard(),
                }
            data["listing_role"] = raw
            s["step"] = "listing_city"
            return {
                "text": "Шаг 2 из 4. Укажите *город*.\n\n_Образец:_ `Москва`",
                "format": "markdown",
                "attachments": visit_card.order_flow_back_keyboard(),
            }
        if step == "listing_city":
            raw = text.strip()
            if len(raw) < 2:
                return {
                    "text": "Проверьте название города.",
                    "format": "markdown",
                    "attachments": visit_card.order_flow_back_keyboard(),
                }
            data["city"] = raw
            s["step"] = "listing_description"
            return {
                "text": (
                    "Шаг 3 из 4. *Описание объявления*: задачи, условия, ставка "
                    "или «по договорённости».\n\n_Минимум 10 символов._"
                ),
                "format": "markdown",
                "attachments": visit_card.order_flow_back_keyboard(),
            }
        if step == "listing_description":
            raw = text.strip()
            if len(raw) < 10:
                return {
                    "text": "Опишите объявление подробнее (минимум 10 символов).",
                    "format": "markdown",
                    "attachments": visit_card.order_flow_back_keyboard(),
                }
            data["listing_description"] = raw
            s["step"] = "listing_timing"
            return {
                "text": (
                    "Шаг 4 из 4. *Срок или когда нужны исполнители*.\n\n"
                    "_Образец:_ `4 промоутера 15–16.06, 10:00–20:00`"
                ),
                "format": "markdown",
                "attachments": visit_card.order_flow_back_keyboard(),
            }
        if step == "listing_timing":
            raw = text.strip()
            if len(raw) < 4:
                return {
                    "text": "Укажите срок или период подробнее.",
                    "format": "markdown",
                    "attachments": visit_card.order_flow_back_keyboard(),
                }
            data["event_date"] = raw
            return _advance_order_contact_step(max_uid, s)
        if step == "listing_confirm":
            return {
                "text": "Используйте кнопки под сообщением.",
                "format": "markdown",
                "attachments": visit_card.listing_confirm_keyboard(),
            }
        if step == "contact_channel_pick":
            return {
                "text": "Выберите способ связи кнопками ниже.",
                "format": "markdown",
                "attachments": visit_card.order_contact_channel_keyboard(),
            }
        if step == "call_time":
            data["call_time"] = text.strip()
            if (data.get("order_kind") or "").strip() == "vacancy_listing":
                s["step"] = "listing_confirm"
                return {
                    "text": _listing_preview_text(data),
                    "format": "markdown",
                    "attachments": visit_card.listing_confirm_keyboard(),
                }
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
                "text": "Выберите варианты кнопками в сообщении выше.",
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }

    if flow == "join":
        if step == "anketa_invite":
            return {
                "text": (
                    "Нажмите *«Заполнить анкету»* под предыдущим сообщением "
                    "или вернитесь в главное меню."
                ),
                "format": "markdown",
                "attachments": visit_card.join_anketa_invite_keyboard(),
            }
        if step == "profession_category":
            return {
                "text": "Продолжите выбор кнопками в сообщении выше.",
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "profession_custom":
            t = text.strip()
            if len(t) < 2:
                return {
                    "text": "Слишком коротко. Укажите название профессии.",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["position"] = t
            s["step"] = "full_name"
            return {
                "text": _basic_info_intro(),
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
            if not visit_join_validators.validate_join_full_name(text):
                return {
                    "text": (
                        "💡 *Укажите полные фамилию, имя и отчество — это нужно для оформления документов.*"
                    ),
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["full_name"] = text.strip()
            s["step"] = "phone"
            return {
                "text": (
                    "📞 *Введите номер телефона:*\n\n"
                    "_Пример: +7 916 123-45-67_"
                ),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "phone":
            v = visit_join_validators.validate_join_phone(text)
            if not v:
                return {
                    "text": (
                        "💡 *Укажите номер в формате мобильного телефона РФ — он нужен для связи по сменам.*"
                    ),
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["phone"] = v
            blocked = _phone_resolve_or_none(max_uid, s, v, "worker")
            if blocked:
                return blocked
            s["step"] = "birth_date"
            return {
                "text": "🎂 *Дата рождения:*\n\n_Пример: 15.05.1990_",
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "birth_date":
            bd = visit_join_validators.parse_birth_date(text)
            today = visit_join_validators.age_check_reference_date()
            if not bd or not visit_join_validators.validate_birth_date_16_50(bd, today):
                return {
                    "text": (
                        "Укажите дату рождения в формате *ДД.ММ.ГГГГ*.\n"
                        "Возраст для работы: от *16* до *50* лет включительно."
                    ),
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["birth_date"] = bd.isoformat()
            s["step"] = "tax_menu"
            return {
                "text": visit_card.text_tax_status_intro(),
                "format": "markdown",
                "attachments": visit_card.join_tax_status_keyboard(),
            }
        if step == "tax_se_inn":
            if not visit_join_validators.validate_inn_digits(text):
                return {
                    "text": "ИНН: введите 10 или 12 цифр.",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["tax_inn"] = re.sub(r"\D", "", text.strip())
            s["step"] = "tax_se_cert"
            return {
                "text": (
                    "Пришлите *справку о постановке на учёт* файлом или чётким фото.\n\n"
                    "Когда документ получен, нажмите *«Отправить на проверку»*.\n"
                    "Кнопка *«📎 Загрузить справку»* — напоминание прикрепить файл."
                ),
                "format": "markdown",
                "attachments": visit_card.tax_se_actions_keyboard(),
            }
        if step == "tax_fl_inn":
            d = re.sub(r"\D", "", text.strip())
            if len(d) != 12:
                return {
                    "text": (
                        "💡 ИНН физлица — *12 цифр*. "
                        "Его можно посмотреть в справке из ФНС или в личном кабинете налогоплательщика."
                    ),
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["tax_inn"] = d
            return _join_begin_identity_chain(s)

        if step == "snils":
            if not visit_join_validators.validate_join_snils(text):
                return {
                    "text": (
                        "💡 Укажите *СНИЛС*: 11 цифр с верной контрольной суммой "
                        "(как в страховом свидетельстве)."
                    ),
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["snils"] = visit_join_validators.normalize_snils_display(text)
            s["step"] = "contact_email"
            return {
                "text": (
                    "📧 *E-mail*\n\n"
                    "Адрес для документов по сменам и правок договоров.\n\n"
                    "_Пример: ivanov@mail.ru_"
                ),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }

        if step == "contact_email":
            em = visit_join_validators.validate_join_contact_email(text)
            if not em:
                return {
                    "text": (
                        "💡 Введите корректный e-mail (латиница, символ @ и домен).\n\n"
                        "_Пример: user@mail.ru_"
                    ),
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["contact_email"] = em
            s["step"] = "gph_bank_name"
            return {
                "text": (
                    "🏦 *Банк для выплат*\n\n"
                    "Полное название банка получателя — как в реквизитах для перевода.\n\n"
                    "_Например: ПАО Сбербанк_"
                ),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }

        if step == "gph_bank_name":
            if not visit_join_validators.validate_gph_bank_name(text):
                return {
                    "text": "💡 Укажите название банка одной строкой (не пустое, до 200 символов).",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["gph_bank_name"] = text.strip()
            s["step"] = "gph_bik"
            return {
                "text": "🔢 *БИК банка*\n\nВведите *9 цифр* без пробелов.",
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }

        if step == "gph_bik":
            if not visit_join_validators.validate_gph_bik(text):
                return {
                    "text": "💡 *БИК* — ровно 9 цифр (без букв и пробелов).",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["gph_bik"] = re.sub(r"\D", "", text.strip())
            s["step"] = "gph_settlement_account"
            return {
                "text": (
                    "💳 *Расчётный счёт (р/с)*\n\n"
                    "Номер счёта получателя — *20 цифр*."
                ),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }

        if step == "gph_settlement_account":
            if not visit_join_validators.validate_gph_settlement_account(text):
                return {
                    "text": "💡 *Р/с* — 20 цифр.",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["gph_settlement_account"] = visit_join_validators.normalize_bank_account_20(text)
            s["step"] = "gph_corr_account"
            return {
                "text": (
                    "📎 *Корреспондентский счёт банка (к/с)*\n\n"
                    "Обычно *20 цифр*. Если не используете к/с при переводах — напишите *нет*."
                ),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }

        if step == "gph_corr_account":
            cr = visit_join_validators.parse_gph_corr_account_optional(text)
            if cr is None:
                return {
                    "text": "💡 *К/с* — 20 цифр или напишите *нет*, если поле не используете.",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["gph_corr_account"] = cr
            s["step"] = "experience_pick"
            return {"notification": "Реквизиты сохранены", **_join_prompt_experience()}

        if step == "portfolio_url":
            raw = text.strip()
            if not visit_join_validators.validate_join_portfolio_https_url(raw):
                return {
                    "text": "Нужна ссылка, начинающаяся с https:// (не длиннее 2048 символов).",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["portfolio_url"] = raw
            data["portfolio_mode"] = "url"
            s["step"] = "selfie"
            return _join_prompt_selfie()

        if step == "portfolio_pdf":
            ref = _brief_file_from_body(message_body)
            if not ref:
                return {
                    "text": "Пришлите PDF одним **документом** (скрепка → Файл).",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["portfolio_pdf_ref"] = ref["url"]
            data["portfolio_pdf_file_id"] = ref["url"]
            data["portfolio_mode"] = "pdf"
            s["step"] = "selfie"
            return _join_prompt_selfie()

        if step == "portfolio_menu":
            return {
                "text": "Выберите вариант кнопками под предыдущим сообщением.",
                "format": "markdown",
                "attachments": visit_card.join_portfolio_menu_keyboard(),
            }

        if step == "tax_ip_inn":
            if not visit_join_validators.validate_inn_digits(text):
                return {
                    "text": "ИНН: введите 10 или 12 цифр.",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["tax_inn"] = re.sub(r"\D", "", text.strip())
            s["step"] = "tax_ip_cert"
            return {
                "text": (
                    "Пришлите *выписку из ЕГРИП* файлом или чётким фото.\n\n"
                    "Затем нажмите *«Отправить на проверку»*."
                ),
                "format": "markdown",
                "attachments": visit_card.tax_ip_actions_keyboard(),
            }
        if step in ("tax_se_cert", "tax_help_cert"):
            ref = _image_ref_from_body(message_body)
            if not ref:
                return {
                    "text": (
                        "Пришлите фото или документ вложением. "
                        "Кнопка *«📎 Загрузить справку»* — подсказка."
                    ),
                    "format": "markdown",
                    "attachments": visit_card.tax_se_actions_keyboard(),
                }
            data["tax_cert_ref"] = ref
            return {
                "text": "Файл получен ✅ Можно нажать «Отправить на проверку».",
                "format": "markdown",
                "attachments": visit_card.tax_se_actions_keyboard(),
            }
        if step == "tax_ip_cert":
            ref = _image_ref_from_body(message_body)
            if not ref:
                return {
                    "text": "Пришлите выписку вложением.",
                    "format": "markdown",
                    "attachments": visit_card.tax_ip_actions_keyboard(),
                }
            data["tax_ip_doc_ref"] = ref
            return {
                "text": "Файл получен ✅ Можно нажать «Отправить на проверку».",
                "format": "markdown",
                "attachments": visit_card.tax_ip_actions_keyboard(),
            }
        if step == "tax_menu":
            return {
                "text": "Выберите налоговый статус кнопками ниже.",
                "format": "markdown",
                "attachments": visit_card.join_tax_status_keyboard(),
            }
        if step == "tax_fl_menu":
            return {
                "text": "Выберите вариант кнопками ниже.",
                "format": "markdown",
                "attachments": visit_card.tax_fl_followup_keyboard(),
            }
        if step == "experience_pick":
            return {
                "text": "Выберите уровень опыта кнопками под предыдущим сообщением.",
                "format": "markdown",
                "attachments": visit_card.experience_level_keyboard(),
            }
        if step == "experience_desc":
            t = text.strip()
            if len(t) < 30:
                return {
                    "text": "Опишите опыт подробнее — минимум 30 символов.",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            if len(t) > 300:
                return {
                    "text": "Максимум 300 символов. Сократите текст.",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["experience_desc"] = t
            data["anketa_bonus_star"] = 1
            s["step"] = "param_height"
            return {
                "text": (
                    "*ВАШИ ПАРАМЕТРЫ*\n\n"
                    "_Эти данные нужны для подбора формы и спецодежды._\n\n"
                    "📏 *Введите ваш рост (см):*\n\n"
                    "_Пример: 175. Допустимо 150–210. Отправьте 0, чтобы пропустить._"
                ),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "param_height":
            v = visit_join_validators.validate_height_cm(text)
            if v is None:
                return {
                    "text": "Укажите целое число сантиметров от 150 до 210 или 0, чтобы пропустить.",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["height_cm"] = v if v else ""
            s["step"] = "param_weight"
            return {
                "text": (
                    "⚖️ *Введите ваш вес (кг):*\n\n"
                    "_Пример: 70. Допустимо 45–120. 0 = пропустить._"
                ),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "param_weight":
            v = visit_join_validators.validate_weight_kg(text)
            if v is None:
                return {
                    "text": "Укажите целое число кг от 45 до 120 или 0, чтобы пропустить.",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["weight_kg"] = v if v else ""
            s["step"] = "param_gender"
            return {
                "text": "*Выберите ваш пол:*",
                "format": "markdown",
                "attachments": visit_card.gender_keyboard(),
            }
        if step == "param_gender":
            return {
                "text": "Выберите пол кнопками ниже.",
                "format": "markdown",
                "attachments": visit_card.gender_keyboard(),
            }
        if step == "param_clothing":
            return {
                "text": "Выберите размер одежды кнопками ниже.",
                "format": "markdown",
                "attachments": visit_card.clothing_size_keyboard(),
            }
        if step == "param_shoe":
            v = visit_join_validators.validate_shoe_size(text)
            if v is None:
                return {
                    "text": "Укажите целый размер обуви от 35 до 48 или 0, чтобы пропустить.",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["shoe_size"] = v if v else ""
            s["step"] = "uniform_choice"
            return {
                "text": (
                    "*👕 ФОРМА ОДЕЖДЫ*\n\n"
                    "_Для разных профессий требования к форме отличаются._"
                ),
                "format": "markdown",
                "attachments": visit_card.uniform_entry_keyboard(),
            }
        if step == "uniform_choice":
            return {
                "text": "Выберите вариант кнопками ниже.",
                "format": "markdown",
                "attachments": visit_card.uniform_entry_keyboard(),
            }
        if step == "medbook_has":
            return {
                "text": "Ответьте кнопками ниже.",
                "format": "markdown",
                "attachments": visit_card.medbook_has_keyboard(),
            }
        if step == "medbook_number":
            num = text.strip()
            if len(num) < 3:
                return {
                    "text": "Укажите номер медкнижки или свяжитесь с менеджером, если номера нет.",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["medbook_number"] = num
            s["step"] = "medbook_expiry"
            return {
                "text": (
                    "Укажите *дату окончания срока действия* медкнижки.\n\n"
                    "_Пример: 31.12.2026_"
                ),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "medbook_expiry":
            d = visit_join_validators.validate_medbook_expiry(text)
            if not d:
                return {
                    "text": "Формат ДД.ММ.ГГГГ, например 31.12.2026",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["medbook_expiry"] = d.isoformat()
            data["medbook_label"] = f"Да, №{data.get('medbook_number', '')}, до {d.isoformat()}"
            s["step"] = "trips"
            return {
                "text": "*Готовы ли вы к командировкам?*",
                "format": "markdown",
                "attachments": visit_card.trips_keyboard(),
            }
        if step == "trips":
            return {
                "text": "Ответьте кнопками ниже.",
                "format": "markdown",
                "attachments": visit_card.trips_keyboard(),
            }
        if step == "skills":
            raw = text.strip()
            skills = "" if raw == "0" else raw
            data["skills"] = skills
            s["step"] = "terms_accept"
            return {
                "text": (
                    "⚖️ Перед загрузкой селфи ознакомьтесь с документами и подтвердите согласие с условиями.\n\n"
                    f"📄 [Политика конфиденциальности]({PRIVACY_POLICY_URL})\n"
                    f"📄 [Пользовательское соглашение]({TERMS_OF_SERVICE_URL})\n\n"
                    "Нажимая «Согласен», вы подтверждаете, что ознакомлены и согласны."
                ),
                "format": "markdown",
                "attachments": visit_card.join_terms_keyboard(),
            }
        if step == "terms_accept":
            return {
                "text": "Используйте кнопки «Согласен» или «Не согласен».",
                "format": "markdown",
                "attachments": visit_card.join_terms_keyboard(),
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
            s["step"] = "passport_sn"
            return {
                "text": (
                    "🪪 *Паспортные данные*\n\n"
                    "Для оформления договоров и пропусков введите *серию и номер паспорта* подряд (10 цифр).\n\n"
                    "_Пример: 4519 123456_"
                ),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "passport_sn":
            raw = text.strip()
            if not visit_join_validators.validate_passport_series_number(raw):
                return {
                    "text": (
                        "💡 *Укажите серию и номер паспорта — 10 цифр (можно с пробелом после 4-й цифры).*"
                    ),
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["passport_sn"] = visit_join_validators.normalize_passport_series_number(raw)
            s["step"] = "passport_issued_by"
            return {
                "text": (
                    "📋 *Кем выдан паспорт*\n\n"
                    "Как в строке *«Кем выдан»* на основном развороте.\n\n"
                    "_Пример: ГУ МВД России по Москве_"
                ),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }

        if step == "passport_issued_by":
            raw = text.strip()
            if not visit_join_validators.validate_passport_issued_by(raw):
                return {
                    "text": (
                        "💡 Укажите подразделение, выдавшее паспорт "
                        "(не короче нескольких слов, без шуток и шаблонов)."
                    ),
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["passport_issued_by"] = raw
            s["step"] = "passport_issued_on"
            return {
                "text": (
                    "📅 *Дата выдачи паспорта*\n\n"
                    "Формат *ДД.ММ.ГГГГ*, как в документе.\n\n"
                    "_Пример: 12.03.2015_"
                ),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }

        if step == "passport_issued_on":
            issue_d = visit_join_validators.parse_birth_date(text)
            bd_join = _join_parse_birth_from_data(data)
            today = visit_join_validators.age_check_reference_date()
            if not issue_d or not visit_join_validators.validate_passport_issue_date(
                issue_d, birth=bd_join, today=today
            ):
                return {
                    "text": (
                        "💡 Дата выдачи в формате ДД.ММ.ГГГГ; "
                        "не раньше даты рождения и не в будущем."
                    ),
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["passport_issued_on"] = issue_d.isoformat()
            s["step"] = "passport_main"
            return {
                "text": (
                    "*📸 Паспорт — основная страница*\n\n"
                    "Для верификации пришлите фото разворота с фото.\n\n"
                    "_Нажмите 📎 → Камера._\n\n"
                    "💡 _Чёткое фото, без бликов, лицо и данные читаемы._"
                ),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "passport_main":
            ref = _image_ref_from_body(message_body)
            if not ref:
                return {
                    "text": "Нужно отправить фото.",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["passport_main_ref"] = ref
            s["step"] = "registration_address"
            return {
                "text": (
                    "🏠 *Адрес регистрации*\n\n"
                    "Полный адрес *одной строкой* (как в паспорте или по ФИАС). "
                    "После этого попросим *фото* страницы с пропиской."
                ),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }

        if step == "registration_address":
            raw = text.strip()
            if not visit_join_validators.validate_registration_address(raw):
                return {
                    "text": (
                        "💡 Укажите полный адрес регистрации текстом "
                        "(несколько слов, без аббревиатур-заглушек)."
                    ),
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["registration_address"] = raw
            s["step"] = "passport_reg"
            return {
                "text": (
                    "*📸 Паспорт — страница с пропиской*\n\n"
                    "Пришлите фото страницы с регистрацией.\n\n"
                    "💡 _Данные не должны быть засвечены._"
                ),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }

        if step == "passport_reg":
            ref = _image_ref_from_body(message_body)
            if not ref:
                return {
                    "text": "Нужно отправить фото.",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["passport_reg_ref"] = ref
            s["step"] = "work_city"
            return {
                "text": (
                    "📍 *Город для подбора смен*\n\n"
                    "Укажите *город*, где вы обычно работаете и живёте.\n\n"
                    "_Например: Москва, Санкт-Петербург, Казань._"
                ),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }

        if step == "work_city":
            raw = text.strip()
            if not visit_join_validators.validate_join_work_city(raw):
                return {
                    "text": "💡 Укажите название города текстом (2–120 символов).",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["city"] = raw
            if visit_join_validators.join_metro_followup_needed(raw):
                s["step"] = "work_metro"
                return {
                    "text": (
                        "🚇 *Метро*\n\n"
                        "Укажите удобную *станцию* или *линию*.\n\n"
                        "_Например: Парк Победы._\n\n"
                        "Если метро не используете — нажмите *Пропустить*."
                    ),
                    "format": "markdown",
                    "attachments": visit_card.work_metro_keyboard(),
                }
            data["metro_station"] = ""
            return _join_go_to_review(s, data)

        if step == "work_metro":
            ok_m, err_m = visit_join_validators.validate_join_metro_station_text(text)
            if not ok_m:
                return {
                    "text": err_m or "Проверьте текст.",
                    "format": "markdown",
                    "attachments": visit_card.work_metro_keyboard(),
                }
            data["metro_station"] = text.strip()
            return _join_go_to_review(s, data)
        if step == "review_submit":
            return {
                "text": "Используйте кнопки под сообщением с проверкой данных.",
                "format": "markdown",
                "attachments": visit_card.join_review_keyboard(),
            }

    return None
