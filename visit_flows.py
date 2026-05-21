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
from datetime import date, datetime, timedelta
from typing import Any

from config import (
    ADMIN_MAX_USER_IDS,
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
from max_attachments import cb_btn, inline_keyboard, link_btn, phone_input_keyboard
from visit_join_anketa_catalog import (
    EXPERIENCE_RATING_TABLE,
    PROFESSION_SLUG_TO_TITLE,
    ProfessionCategory,
)
from funnel_store import funnel_touch_complete
from funnel_db import (
    count_agency_visit_orders_funnel_excluding,
    list_agency_visit_orders_funnel_page,
    get_agency_visit_order_for_admin,
    apply_visit_order_crm_stage_from_admin,
    get_agency_crm_card_pipeline_stage,
    get_users_phone_duplicates_metrics,
    get_visitcard_stats,
    get_worker_cooperation_mode_metrics,
    list_visit_rows,
    list_open_shifts_admin_max,
    get_shift_admin_max,
    list_shift_assignments_for_shift_max,
    list_assignable_workers_for_shift_max,
    assign_worker_to_shift_max,
    list_projects_admin_max,
    get_project_admin_max,
    list_shift_assignments_recent_max,
    list_worker_payments_recent_max,
    get_worker_payment_admin_max,
    list_workers_admin_max,
    search_workers_admin_max,
    get_worker_admin_max,
    get_worker_assignment_stats_max,
    list_worker_payments_for_worker_max,
    list_worker_shifts_max,
    get_worker_shift_assignment_max,
    confirm_worker_shift_max,
    checkin_worker_shift_max,
    checkout_worker_shift_max,
    start_worker_break_max,
    stop_worker_break_max,
    get_active_break_max,
    get_worker_break_stats_max,
    auto_close_expired_breaks_max,
    get_worker_beacon_state_max,
    enable_worker_beacon_max,
    disable_worker_beacon_max,
    resolve_tg_id_for_max_user,
    update_worker_payment_status_max,
    log_admin_action_max,
    list_admin_logs_max,
    get_admin_hub_counters_max,
    get_company_subscription_metrics_max,
    list_expiring_company_subscriptions_max,
    list_expired_company_subscriptions_max,
    get_company_subscription_max,
    count_projects_for_company_max,
    admin_extend_company_subscription_days_max,
    admin_set_company_subscription_grace_max,
    COOPERATION_MODE_PLATFORM,
    get_max_worker_cooperation_mode,
    has_max_active_executor_profile,
    is_max_visit_client_registered,
    is_max_visit_client_verified,
    user_has_prior_bot_pd_context_max,
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
from visit_phone_login_log import OUTCOME_LABELS_RU, list_visit_phone_login_log

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
_PLATFORM_GATE_BLOCKS_TOTAL = 0
_PLATFORM_GATE_BLOCKS_BY_USER: dict[int, int] = {}


def get_platform_gate_metrics() -> dict[str, int]:
    return {
        "platform_gate_blocks_total": int(_PLATFORM_GATE_BLOCKS_TOTAL),
        "platform_gate_users_count": int(len(_PLATFORM_GATE_BLOCKS_BY_USER)),
    }


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


def _role_entry_text() -> str:
    return (
        "*У вас уже есть регистрация в Promostaff?*\n\n"
        "Если вы уже проходили регистрацию в Telegram или MAX — нажмите "
        "«Уже регистрировался» и укажите тот же номер телефона.\n\n"
        "Если впервые — «Регистрируюсь впервые»."
    )


def _role_entry_screen(role: str) -> dict[str, Any]:
    return {
        "text": _role_entry_text(),
        "format": "markdown",
        "attachments": visit_card.role_entry_keyboard(role),
    }


def _start_role_entry_phone(max_uid: int, role: str) -> dict[str, Any]:
    clear_session(max_uid)
    SESSIONS[max_uid] = {
        "flow": "role_entry",
        "step": "phone",
        "data": {"intended_role": role},
    }
    return {
        "notification": "Вход по телефону",
        "text": (
            "📞 *Укажите номер телефона*\n\n"
            "Нажмите *Поделиться контактом* или введите номер вручную.\n\n"
            "_Пример: +7 916 123-45-67_"
        ),
        "format": "markdown",
        "attachments": phone_input_keyboard(),
    }


def _begin_client_visit_registration_new(max_uid: int) -> dict[str, Any]:
    clear_session(max_uid)
    SESSIONS[max_uid] = {"flow": "client_visit", "step": "consent", "data": {}}
    return {
        "notification": "Меню заказчика",
        "text": _consent_gate_text("меню заказчика"),
        "format": "markdown",
        "attachments": visit_card.consent_gate_keyboard("client_visit"),
    }


def _show_join_team_intro(max_uid: int) -> dict[str, Any]:
    clear_session(max_uid)
    return {
        "text": visit_card.text_join_team(),
        "format": "markdown",
        "attachments": visit_card.join_team_intro_keyboard(),
    }


def _extract_phone_from_incoming(
    text: str, message_body: dict[str, Any] | None
) -> str | None:
    from max_contact_phone import contact_from_message_body

    if message_body:
        raw, _verified = contact_from_message_body(message_body)
        if raw:
            v = visit_join_validators.validate_join_phone_mobile_rf(raw)
            if v:
                return v
    if text:
        return visit_join_validators.validate_join_phone_mobile_rf(text)
    return None


def clear_session(max_uid: int) -> None:
    SESSIONS.pop(max_uid, None)


def debug_session_text(max_uid: int) -> str:
    """Короткий debug-снимок FSM сессии по user_id."""
    s = SESSIONS.get(int(max_uid))
    if not isinstance(s, dict):
        return "🧪 FSM: активной сессии нет."
    flow = str(s.get("flow") or "—")
    step = str(s.get("step") or "—")
    data = s.get("data")
    data_keys: list[str] = []
    if isinstance(data, dict):
        data_keys = [str(k) for k in data.keys()]
    preview = ", ".join(data_keys[:16]) if data_keys else "—"
    if len(data_keys) > 16:
        preview += ", …"
    return (
        "🧪 FSM debug\n\n"
        f"user_id: `{int(max_uid)}`\n"
        f"flow: `{flow}`\n"
        f"step: `{step}`\n"
        f"data_keys: {len(data_keys)}\n"
        f"keys: {preview}"
    )


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


def _location_from_body(message_body: dict[str, Any] | None, text: str | None = None) -> tuple[float, float] | None:
    if message_body:
        loc = message_body.get("location")
        if isinstance(loc, dict):
            lat = loc.get("lat") or loc.get("latitude")
            lng = loc.get("lng") or loc.get("lon") or loc.get("longitude")
            try:
                if lat is not None and lng is not None:
                    return float(lat), float(lng)
            except (TypeError, ValueError):
                pass
        raw = message_body.get("attachments")
        if raw is None and isinstance(message_body.get("attachment"), dict):
            raw = [message_body["attachment"]]
        if isinstance(raw, list):
            for a in raw:
                if not isinstance(a, dict):
                    continue
                t = (a.get("type") or "").lower()
                if t not in ("location", "geo", "geopoint"):
                    continue
                p = a.get("payload")
                if isinstance(p, dict):
                    lat = p.get("lat") or p.get("latitude")
                    lng = p.get("lng") or p.get("lon") or p.get("longitude")
                    try:
                        if lat is not None and lng is not None:
                            return float(lat), float(lng)
                    except (TypeError, ValueError):
                        continue
    txt = (text or "").strip()
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*[,; ]\s*(-?\d+(?:\.\d+)?)", txt)
    if not m:
        return None
    try:
        return float(m.group(1)), float(m.group(2))
    except (TypeError, ValueError):
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
    global _PLATFORM_GATE_BLOCKS_TOTAL
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
        if get_max_worker_cooperation_mode(max_uid) == COOPERATION_MODE_PLATFORM:
            _PLATFORM_GATE_BLOCKS_TOTAL += 1
            _PLATFORM_GATE_BLOCKS_BY_USER[int(max_uid)] = int(
                _PLATFORM_GATE_BLOCKS_BY_USER.get(int(max_uid), 0)
            ) + 1
            return {
                "notification": "Платформенный контур",
                "text": (
                    "*Профиль исполнителя подтверждён.*\n\n"
                    "Для аккаунта включён платформенный режим: агентские смены и рассылки сейчас недоступны.\n"
                    "Откройте «Кабинет на сайте» или напишите менеджеру для смены режима."
                ),
                "format": "markdown",
                "attachments": visit_card.main_menu_keyboard(),
            }
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
    if user_has_prior_bot_pd_context_max(max_uid):
        SESSIONS[max_uid] = {
            "flow": "client_visit",
            "step": "company_name",
            "data": {
                "order_consent_accepted": True,
                "order_entry": "visit_client_register",
            },
        }
        return {
            "notification": "Меню заказчика",
            "text": (
                "Давайте познакомимся.\n\n"
                "Укажите *название юрлица заказчика*.\n\n"
                "_Образец:_ `ООО «Ромашка»`"
            ),
            "format": "markdown",
            "attachments": visit_card.back_to_main_keyboard(),
        }
    clear_session(max_uid)
    return _role_entry_screen("client")


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


def show_join_team(max_uid: int) -> dict[str, Any]:
    """Меню исполнителя — сначала вход по телефону (паритет TG)."""
    blocked = _join_entry_blocked(max_uid)
    if blocked:
        return blocked
    clear_session(max_uid)
    return _role_entry_screen("worker")


def show_requirements(max_uid: int) -> dict[str, Any]:
    clear_session(max_uid)
    return {
        "text": visit_card.text_requirements(),
        "format": "markdown",
        "attachments": visit_card.join_team_back_keyboard(),
    }


def show_vacancies_list(max_uid: int) -> dict[str, Any]:
    blocked = _join_entry_blocked(max_uid)
    if blocked:
        return blocked
    clear_session(max_uid)
    return {
        "text": visit_card.vacancies_summary_markdown(),
        "format": "markdown",
        "attachments": visit_card.vacancies_list_keyboard(),
    }


def show_vacancy_detail(max_uid: int, payload: str) -> dict[str, Any] | None:
    blocked = _join_entry_blocked(max_uid)
    if blocked:
        return blocked
    slug = payload.replace("vac_view_", "", 1).strip().lower()
    body = visit_card.vacancy_detail_markdown(slug)
    if not body:
        return None
    clear_session(max_uid)
    return {
        "text": body,
        "format": "markdown",
        "attachments": visit_card.vacancy_detail_keyboard(slug),
    }


def start_fill_anketa(max_uid: int) -> dict[str, Any]:
    """Запуск полной анкеты исполнителя — как TG begin_executor_full_anketa."""
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
        "text": _consent_gate_text("регистрация исполнителя"),
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
        "text": _consent_gate_text("регистрация исполнителя"),
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


def _profession_summary_markdown(titles: list[str]) -> str:
    if not titles:
        return "*ПРОФЕССИИ*\n\nСписок пуст — выберите профессию в категории."
    lines: list[str] = []
    for i, t in enumerate(titles, start=1):
        mark = " — *основная*" if i == 1 else ""
        lines.append(f"{i}. {t}{mark}")
    body = "\n".join(lines)
    return (
        "*ПРОФЕССИИ*\n\n"
        f"{body}\n\n"
        "Первая в списке — *основная* (её видят в профиле и используют в подборе по умолчанию).\n\n"
        "Можно добавить ещё роль или перейти к ФИО."
    )


def _append_join_profession_title(data: dict[str, Any], title: str) -> tuple[list[str], bool]:
    t = (title or "").strip()
    if len(t) < 2:
        return [], False
    raw = list(data.get("join_profession_titles") or [])
    if not raw and (data.get("position") or "").strip():
        raw = [str(data.get("position") or "").strip()]
    if any(x.strip().lower() == t.lower() for x in raw):
        return raw, False
    raw.append(t)
    data["join_profession_titles"] = raw
    data["position"] = raw[0]
    return raw, True


def _join_goto_profession_summary(
    s: dict[str, Any], data: dict[str, Any], *, notification: str = ""
) -> dict[str, Any]:
    titles = list(data.get("join_profession_titles") or [])
    s["step"] = "profession_summary"
    out: dict[str, Any] = {
        "text": _profession_summary_markdown(titles),
        "format": "markdown",
        "attachments": visit_card.profession_summary_keyboard(
            edit_mode=bool(data.get("join_edit_mode"))
        ),
    }
    if notification:
        out["notification"] = notification
    return out


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


def _join_profession_display(data: dict[str, Any]) -> str:
    titles = data.get("join_profession_titles")
    if isinstance(titles, list) and titles:
        return ", ".join(str(x).strip() for x in titles if str(x).strip())
    return (data.get("position") or "").strip()


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
        f"*Профессии:* {_join_profession_display(data) or m}\n"
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


def _client_visit_payload_for_save(data: dict[str, Any]) -> dict[str, Any]:
    """Чистый payload регистрации заказчика без полей мастера заказа/КП."""
    allowed_fields = (
        "company_name",
        "contact_name",
        "position_in_org",
        "phone",
        "inn",
        "contact_email",
        "canonical_user_tg_id",
    )
    out: dict[str, Any] = {}
    for key in allowed_fields:
        val = data.get(key)
        if val is None:
            continue
        out[key] = val.strip() if isinstance(val, str) else val
    return out


def _client_visit_preview_text(data: dict[str, Any]) -> str:
    inn = (data.get("inn") or "").strip()
    return (
        "📋 *Проверка данных*\n\n"
        f"🏢 Организация: {data.get('company_name', '')}\n"
        f"🧾 ИНН: {inn}\n"
        f"👤 Контактное лицо: {data.get('contact_name', '')}\n"
        f"💼 Должность: {data.get('position_in_org', '')}\n"
        f"📞 Телефон: {data.get('phone', '')}\n"
        f"✉️ Email: {data.get('contact_email', '')}\n\n"
        "Всё верно?\n\n"
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


FUNNEL_PAGE_SIZE = 10
VISIT_ORDER_KIND_LABELS = {
    "cp_request": "КП",
    "quick_estimate": "Срочный",
    "vacancy_listing": "Объявление",
}
CRM_STAGE_LABELS: dict[str, str] = {
    "new": "Новая",
    "kp_prep": "Готовим КП",
    "client_review": "Клиент рассматривает",
    "invoice_issued": "Счёт выставлен",
    "invoice_paid": "Счёт оплачен",
    "approved_project": "В работу",
    "closed_lost": "Закрыто (проиграно)",
    "manager_work": "В работе менеджера",
    "project_active": "Проект активен",
    "done": "Завершено",
    "cancelled": "Отменено",
}
KP_STAGES_MAX: tuple[str, ...] = (
    "new",
    "kp_prep",
    "client_review",
    "invoice_issued",
    "invoice_paid",
    "approved_project",
    "closed_lost",
)
URGENT_STAGES_MAX: tuple[str, ...] = (
    "new",
    "manager_work",
    "invoice_issued",
    "invoice_paid",
    "project_active",
    "done",
    "cancelled",
)
PAYMENT_STATUS_LABELS_RU: dict[str, str] = {
    "pending": "⏳ Ожидает",
    "approved": "✅ Согласована",
    "paid": "💵 Выплачена",
    "cancelled": "🚫 Отменена",
}
ASSIGNMENT_STATUS_LABELS_RU: dict[str, str] = {
    "assigned": "Назначена",
    "confirmed": "Подтверждена",
    "checked_in": "На смене",
    "checked_out": "Завершена",
    "cancelled": "Отменена",
}
BREAK_TYPE_LABELS_RU: dict[str, str] = {
    "lunch": "Обед",
    "smoke": "Перекур",
    "tech": "Тех. перерыв",
}


def _worker_shift_list_text(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "*Мои смены*\n\nНазначений пока нет."
    lines = ["*Мои смены*", ""]
    for row in rows[:20]:
        sid = int(row.get("shift_id") or 0)
        st = str(row.get("assignment_status") or "")
        lines.append(
            f"• #{sid} · {(row.get('shift_date') or '—')} {row.get('start_time') or '—'}-{row.get('end_time') or '—'}\n"
            f"  {row.get('project_name') or 'Проект'} · {ASSIGNMENT_STATUS_LABELS_RU.get(st, st or '—')}"
        )
    return "\n".join(lines)[:3900]


def _worker_shift_list_keyboard(rows: list[dict[str, Any]]) -> list[dict]:
    kb_rows: list[list[dict]] = []
    for row in rows[:20]:
        sid = int(row.get("shift_id") or 0)
        kb_rows.append([cb_btn(f"📍 Смена #{sid}", f"worker_shift_{sid}")])
    kb_rows.append([cb_btn("🔙 Меню исполнителя", "main_menu")])
    return inline_keyboard(kb_rows)


def _worker_shift_detail_text(card: dict[str, Any], active_break: dict[str, Any] | None, bstats: dict[str, int]) -> str:
    st = str(card.get("assignment_status") or "")
    text = (
        f"*Смена #{int(card.get('shift_id') or 0)}*\n\n"
        f"Проект: {card.get('project_name') or '—'}\n"
        f"Дата: {card.get('shift_date') or '—'}\n"
        f"Время: {card.get('start_time') or '—'} - {card.get('end_time') or '—'}\n"
        f"Локация: {card.get('location') or '—'}\n"
        f"Статус: {ASSIGNMENT_STATUS_LABELS_RU.get(st, st or '—')}\n"
        f"Чекин: {card.get('checkin_time') or '—'}\n"
        f"Чекаут: {card.get('checkout_time') or '—'}\n"
        f"Отработано (мин): {int(card.get('worked_minutes') or 0)}\n"
        f"Перерывы: обед {int(bstats.get('lunch_count', 0))}, "
        f"перекур {int(bstats.get('smoke_count', 0))}, "
        f"тех {int(bstats.get('tech_count', 0))}"
    )
    if active_break:
        bt = str(active_break.get("break_type") or "")
        text += (
            f"\n\n🟡 Активный перерыв: {BREAK_TYPE_LABELS_RU.get(bt, bt or '—')} "
            f"(старт: {active_break.get('started_at') or '—'})"
        )
    return text[:3900]


def _worker_shift_detail_keyboard(card: dict[str, Any], active_break: dict[str, Any] | None) -> list[dict]:
    sid = int(card.get("shift_id") or 0)
    st = str(card.get("assignment_status") or "")
    rows: list[list[dict]] = []
    if st == "assigned":
        rows.append([cb_btn("✅ Подтвердить смену", f"worker_shift_confirm_{sid}")])
    if st in {"confirmed"}:
        rows.append([cb_btn("📍 Чекин", f"worker_shift_checkin_{sid}")])
    if st in {"checked_in"}:
        rows.append([cb_btn("🏁 Чекаут", f"worker_shift_checkout_{sid}")])
        rows.append([cb_btn("☕ Перерывы", f"worker_break_menu_{sid}")])
    if active_break:
        rows.append([cb_btn("⏹ Завершить перерыв", f"worker_break_stop_{sid}")])
    rows.append([cb_btn("🔙 К сменам", "worker_reg_shifts")])
    rows.append([cb_btn("🔙 Меню исполнителя", "main_menu")])
    return inline_keyboard(rows)


def _format_assignment_compact_lines_max(assignments: list[dict[str, Any]], limit: int = 12) -> str:
    status_labels = {
        "assigned": "🟡 assigned",
        "confirmed": "🟦 confirmed",
        "checked_in": "🟢 checked_in",
        "checked_out": "⚪ checked_out",
        "cancelled": "🔴 cancelled",
    }
    rows: list[str] = []
    for a in (assignments or [])[: max(1, int(limit))]:
        st = str(a.get("status") or "").strip().lower()
        worker = str(a.get("worker_name") or a.get("worker_tg_id") or "—").strip()
        rows.append(f"• {worker} — {status_labels.get(st, st or '—')}")
    if not rows:
        return "Назначений пока нет."
    return "\n".join(rows)


def _ops_shift_risk_lines_max(
    card: dict[str, Any],
    status_counts: dict[str, int],
    *,
    now: datetime | None = None,
) -> list[str]:
    risks: list[str] = []
    n = now or datetime.now()
    assigned = int(status_counts.get("assigned", 0))
    confirmed = int(status_counts.get("confirmed", 0))
    checked_in = int(status_counts.get("checked_in", 0))
    checked_out = int(status_counts.get("checked_out", 0))
    total_assigned = assigned + confirmed + checked_in + checked_out
    workers_needed = int(card.get("workers_needed") or 0)
    bounds = _shift_bounds_from_card(card)
    if not bounds:
        return risks
    dt_start, dt_end = bounds
    mins_to_start = int((dt_start - n).total_seconds() // 60)
    mins_after_end = int((n - dt_end).total_seconds() // 60)
    if 0 <= mins_to_start <= 120 and assigned > 0:
        risks.append(f"🔴 До старта ~{mins_to_start} мин, но {assigned} исполнителей ещё без подтверждения.")
    if workers_needed > 0 and total_assigned < workers_needed and 0 <= mins_to_start <= 180:
        risks.append(f"🟠 До старта ~{mins_to_start} мин, недобор персонала: {total_assigned}/{workers_needed}.")
    if -180 <= mins_to_start < 0 and checked_in == 0 and total_assigned > 0:
        risks.append("🔴 Смена уже началась, но нет ни одного check-in.")
    if mins_after_end >= 30 and checked_in > 0:
        risks.append(f"🟠 После конца смены прошло {mins_after_end} мин, есть незакрытые check-out.")
    return risks


def _is_unconfirmed_ping_window_max(card: dict[str, Any], *, now: datetime | None = None) -> tuple[bool, str]:
    n = now or datetime.now()
    bounds = _shift_bounds_from_card(card)
    if not bounds:
        return False, "Не удалось определить время старта смены."
    dt_start, _dt_end = bounds
    mins_to_start = int((dt_start - n).total_seconds() // 60)
    if mins_to_start > 120:
        return False, f"До старта ещё {mins_to_start} мин — вне критичного окна (<=120)."
    if mins_to_start < -180:
        return False, f"Смена началась более {-mins_to_start} мин назад — массовый пинг уже неактуален."
    return True, ""


def _as_naive_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    raw = str(value).strip()
    if not raw:
        return None
    if "T" not in raw and " " in raw:
        raw = raw.replace(" ", "T", 1)
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _shift_bounds_from_card(card: dict[str, Any]) -> tuple[datetime, datetime] | None:
    d = str(card.get("shift_date") or "").strip()
    st = str(card.get("start_time") or "").strip()
    et = str(card.get("end_time") or "").strip()
    if not d or not st or not et:
        return None
    dt_start = _as_naive_dt(f"{d}T{st}")
    dt_end = _as_naive_dt(f"{d}T{et}")
    if not dt_start or not dt_end:
        return None
    if dt_end <= dt_start:
        dt_end = dt_end + timedelta(days=1)
    return dt_start, dt_end


def _shift_duration_hours_from_card(card: dict[str, Any]) -> int:
    bounds = _shift_bounds_from_card(card)
    if not bounds:
        return 1
    dt_start, dt_end = bounds
    return max(1, int((dt_end - dt_start).total_seconds() // 3600))


def _break_start_validation_message_max(
    card: dict[str, Any],
    stats: dict[str, int],
    break_type: str,
) -> str | None:
    now = datetime.now()
    checkin = _as_naive_dt(card.get("checkin_time"))
    bounds = _shift_bounds_from_card(card)
    if break_type == "lunch":
        if int(stats.get("lunch_count", 0)) >= 1:
            return "Обеденный перерыв можно взять только один раз за смену."
        if not checkin or (now - checkin).total_seconds() < 2 * 3600:
            return "Обед доступен не раньше чем через 2 часа после чек-ина."
        if bounds:
            _, dt_end = bounds
            if (dt_end - now).total_seconds() < 2 * 3600:
                return "Обед недоступен в последние 2 часа смены."
    if break_type == "smoke":
        if not checkin or (now - checkin).total_seconds() < 3600:
            return "Перекур доступен не раньше чем через 1 час после чек-ина."
        if bounds:
            _, dt_end = bounds
            if (dt_end - now).total_seconds() < 3600:
                return "Перекур недоступен в последний час смены."
        max_smokes = max(0, _shift_duration_hours_from_card(card) - 1)
        if int(stats.get("smoke_count", 0)) >= max_smokes:
            return f"Лимит перекуров исчерпан: {max_smokes}."
    if break_type == "tech":
        if not checkin or (now - checkin).total_seconds() < 15 * 60:
            return "Тех. перерыв доступен не раньше чем через 15 минут после чек-ина."
    return None


def _is_admin_max_uid(max_uid: int) -> bool:
    return int(max_uid) in set(ADMIN_MAX_USER_IDS or [])


def _admin_denied_reply(max_uid: int) -> dict[str, Any]:
    return {
        "notification": "Недоступно",
        "text": "Этот раздел доступен только администраторам агентства.",
        "format": "markdown",
        "attachments": visit_card.main_menu_keyboard(max_uid),
    }


def _funnel_kind_title(kind: str) -> str:
    return {
        "all": "Воронка заказов",
        "kp": "Воронка KPI/KP",
        "urgent": "Воронка срочных заказов",
    }.get(kind, "Воронка заказов")


def _funnel_order_kind_for_tab(kind: str) -> str | None:
    if kind == "kp":
        return "cp_request"
    if kind == "urgent":
        return "__urgent__"
    return None


def _order_stage_callback(order_id: int, stage: str) -> str:
    return f"admin_order_stage_{int(order_id)}_{(stage or '').strip()}"


def _parse_order_stage_callback(payload: str) -> tuple[int, str] | None:
    m = re.match(r"^admin_order_stage_(\d+)_(.+)$", payload or "")
    if not m:
        return None
    return int(m.group(1)), m.group(2).strip().lower()


def _parse_funnel_nav_callback(payload: str) -> tuple[str, int, str] | None:
    m = re.match(r"^admin_funnel__([a-z_]+)__(-?\d+)(?:__([a-z_]+))?$", payload or "")
    if not m:
        return None
    kind = (m.group(1) or "").strip().lower()
    if kind not in ("all", "kp", "urgent"):
        return None
    stage = (m.group(3) or "all").strip().lower()
    return kind, max(0, int(m.group(2))), (stage or "all")


def _parse_order_detail_callback(payload: str) -> int | None:
    m = re.match(r"^admin_order_detail_(\d+)$", payload or "")
    if not m:
        return None
    return int(m.group(1))


def _parse_worker_detail_callback(payload: str) -> int | None:
    m = re.match(r"^admin_hrm_worker_detail_(\d+)$", payload or "")
    if not m:
        return None
    return int(m.group(1))


def _parse_payment_status_callback(payload: str) -> tuple[int, str] | None:
    m = re.match(r"^admin_hrm_paystatus_(\d+)_([a-z_]+)$", payload or "")
    if not m:
        return None
    return int(m.group(1)), (m.group(2) or "").strip().lower()


def _subs_rows_by_mode_max(mode: str) -> list[dict[str, Any]]:
    m = (mode or "expiring").strip().lower()
    if m == "expired":
        return list_expired_company_subscriptions_max(limit=30)
    return list_expiring_company_subscriptions_max(days=7, limit=30)


def _subs_list_keyboard_max(mode: str, rows: list[dict[str, Any]]) -> list[dict]:
    m = (mode or "expiring").strip().lower()
    toggle_text = "⚠️ Только истекшие" if m == "expiring" else "⏳ Истекают 7 дней"
    toggle_mode = "expired" if m == "expiring" else "expiring"
    kb_rows: list[list[dict]] = [[cb_btn(toggle_text, f"admin_sys_subs_mode_{toggle_mode}")]]
    for row in rows[:20]:
        cid = int(row.get("company_id") or 0)
        cname = (row.get("company_name") or f"Компания #{cid}").strip()
        kb_rows.append([cb_btn(f"🏢 {cname[:42]}", f"admin_sys_subs_company_{cid}_{m}")])
    kb_rows.append([cb_btn("🔙 System", "admin_hub_system")])
    return inline_keyboard(kb_rows)


def _subs_list_text_max(mode: str, rows: list[dict[str, Any]]) -> str:
    m = (mode or "expiring").strip().lower()
    if m == "expired":
        title = "*Подписки (только истекшие)*"
        empty = "Истекших подписок нет."
        until_label = "истекла"
    else:
        title = "*Подписки (истекают 7 дней)*"
        empty = "На горизонте 7 дней истекающих подписок нет."
        until_label = "до"
    if not rows:
        return f"{title}\n\n{empty}"
    lines = [title, ""]
    for row in rows[:30]:
        cid = int(row.get("company_id") or 0)
        cname = (row.get("company_name") or f"Компания #{cid}").strip()
        plan = (row.get("plan_code") or "legacy").strip() or "legacy"
        ends_at = row.get("ends_at") or "—"
        used = int(row.get("projects_used") or 0)
        limit = row.get("projects_limit")
        quota = f"{used}/∞" if limit is None else f"{used}/{int(limit)}"
        lines.append(
            f"• #{cid} · {cname}\n"
            f"  план: {plan} · проекты: {quota}\n"
            f"  {until_label}: {ends_at}"
        )
    return "\n".join(lines)[:3900]


def _parse_subs_company_cb_max(payload: str) -> tuple[int, str] | None:
    m = re.match(r"^admin_sys_subs_company_(\d+)_(expiring|expired)$", payload or "")
    if not m:
        return None
    return int(m.group(1)), str(m.group(2))


def _parse_subs_action_cb_max(payload: str) -> tuple[int, str, str] | None:
    m = re.match(r"^admin_sys_subs_act_(\d+)_(extend|grace)_(expiring|expired)$", payload or "")
    if not m:
        return None
    return int(m.group(1)), str(m.group(2)), str(m.group(3))


def _parse_subs_confirm_cb_max(payload: str) -> tuple[int, str, str] | None:
    m = re.match(r"^admin_sys_subs_confirm_(\d+)_(extend|grace)_(expiring|expired)$", payload or "")
    if not m:
        return None
    return int(m.group(1)), str(m.group(2)), str(m.group(3))


def _subs_company_detail_text_max(company_id: int) -> str:
    cid = int(company_id)
    sub = get_company_subscription_max(cid)
    if not sub:
        return (
            f"*Подписка компании #{cid}*\n\n"
            "Строка подписки не создана. Можно выдать grace или продлить +30 дней."
        )
    used = int(count_projects_for_company_max(cid))
    limit = sub.get("projects_limit")
    quota = f"{used}/∞" if limit is None else f"{used}/{int(limit)}"
    return (
        f"*Подписка компании #{cid}*\n\n"
        f"План: {sub.get('plan_code') or 'legacy'}\n"
        f"Статус: {sub.get('status') or 'active'}\n"
        f"Проекты: {quota}\n"
        f"Начало: {sub.get('starts_at') or '—'}\n"
        f"Окончание: {sub.get('ends_at') or '—'}"
    )


def _subs_company_detail_keyboard_max(company_id: int, mode: str) -> list[dict]:
    cid = int(company_id)
    m = (mode or "expiring").strip().lower()
    return inline_keyboard(
        [
            [cb_btn("➕ Продлить +30 дней", f"admin_sys_subs_confirm_{cid}_extend_{m}")],
            [cb_btn("🟡 Выдать grace (7д)", f"admin_sys_subs_confirm_{cid}_grace_{m}")],
            [cb_btn("🔙 К списку", f"admin_sys_subs_mode_{m}")],
            [cb_btn("🔙 System", "admin_hub_system")],
        ]
    )


def _subs_confirm_text_max(company_id: int, action: str) -> str:
    cid = int(company_id)
    act = (action or "").strip().lower()
    label = "Продлить +30 дней" if act == "extend" else "Выдать grace (7 дней)"
    return (
        "*Подтвердите действие*\n\n"
        f"Компания: #{cid}\n"
        f"Действие: {label}\n\n"
        "После подтверждения подписка будет изменена сразу."
    )


def _subs_confirm_keyboard_max(company_id: int, action: str, mode: str) -> list[dict]:
    cid = int(company_id)
    act = (action or "").strip().lower()
    m = (mode or "expiring").strip().lower()
    return inline_keyboard(
        [
            [cb_btn("✅ Подтвердить", f"admin_sys_subs_act_{cid}_{act}_{m}")],
            [cb_btn("❌ Отмена", f"admin_sys_subs_company_{cid}_{m}")],
        ]
    )


def _order_stage_buttons(order_id: int, order_kind: str) -> list[list[dict]]:
    stages = KP_STAGES_MAX if (order_kind or "").strip() == "cp_request" else URGENT_STAGES_MAX
    rows: list[list[dict]] = []
    row: list[dict] = []
    for stage in stages:
        row.append(cb_btn(CRM_STAGE_LABELS.get(stage, stage), _order_stage_callback(order_id, stage)))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


def _stage_presets_for_kind(kind: str) -> tuple[str, ...]:
    if kind == "kp":
        return ("all", "new", "kp_prep", "invoice_issued", "invoice_paid")
    if kind == "urgent":
        return ("all", "new", "manager_work", "invoice_issued", "invoice_paid")
    return ("all", "new", "invoice_issued", "invoice_paid")


def _render_admin_funnel_message(*, kind: str, page: int, stage: str = "all") -> dict[str, Any]:
    order_kind = _funnel_order_kind_for_tab(kind)
    stage_filter = (stage or "all").strip().lower()
    total = count_agency_visit_orders_funnel_excluding(order_kind=order_kind, stage=stage_filter)
    if total <= 0:
        return {
            "notification": "Пусто",
            "text": f"*{_funnel_kind_title(kind)}*\n\nФильтр стадии: `{stage_filter}`\n\nПока заявок нет.",
            "format": "markdown",
            "attachments": inline_keyboard(
                [
                    [cb_btn("🔙 CRM", "admin_hub_crm")],
                ]
            ),
        }
    max_page = max(0, (total - 1) // FUNNEL_PAGE_SIZE)
    current_page = max(0, min(int(page), max_page))
    rows = list_agency_visit_orders_funnel_page(
        order_kind=order_kind,
        stage=stage_filter,
        limit=FUNNEL_PAGE_SIZE,
        offset=current_page * FUNNEL_PAGE_SIZE,
    )
    lines = [
        f"*{_funnel_kind_title(kind)}*",
        f"Стадия: `{stage_filter}`",
        f"Страница {current_page + 1}/{max_page + 1} · всего {total}",
        "",
    ]
    kb_rows: list[list[dict]] = []
    for row in rows:
        oid = int(row.get("id") or 0)
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        if not isinstance(payload, dict):
            payload = {}
        kind_label = VISIT_ORDER_KIND_LABELS.get(
            (payload.get("order_kind") or "quick_estimate").strip(),
            "Заявка",
        )
        event_type = (payload.get("event_type") or "—").strip()
        city = (payload.get("city") or "—").strip()
        status = (row.get("status") or "new").strip()
        lines.append(f"• #{oid} · {kind_label} · {event_type}, {city} · `{status}`")
        kb_rows.append([cb_btn(f"⚙️ Заявка #{oid}", f"admin_order_detail_{oid}")])
    nav_row: list[dict] = []
    if current_page > 0:
        nav_row.append(cb_btn("◀️", f"admin_funnel__{kind}__{current_page - 1}__{stage_filter}"))
    if current_page < max_page:
        nav_row.append(cb_btn("▶️", f"admin_funnel__{kind}__{current_page + 1}__{stage_filter}"))
    if nav_row:
        kb_rows.append(nav_row)
    stage_buttons: list[dict] = []
    for st in _stage_presets_for_kind(kind):
        label = "Все" if st == "all" else CRM_STAGE_LABELS.get(st, st)
        if st == stage_filter:
            label = f"• {label}"
        stage_buttons.append(cb_btn(label, f"admin_funnel__{kind}__0__{st}"))
    kb_rows.append(stage_buttons)
    kb_rows.append([cb_btn("🔙 CRM", "admin_hub_crm")])
    return {
        "notification": " ",
        "text": "\n".join(lines)[:3900],
        "format": "markdown",
        "attachments": inline_keyboard(kb_rows),
    }


def _render_admin_order_detail(order_id: int) -> dict[str, Any]:
    row = get_agency_visit_order_for_admin(int(order_id))
    if not row:
        return {
            "notification": "Не найдено",
            "text": "Заявка не найдена.",
            "format": "markdown",
            "attachments": visit_card.admin_hub_crm_keyboard(),
        }
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    if not isinstance(payload, dict):
        payload = {}
    oid = int(row.get("id") or 0)
    status = (row.get("status") or "new").strip()
    order_kind = (payload.get("order_kind") or "quick_estimate").strip()
    crm_stage = get_agency_crm_card_pipeline_stage(oid)
    stage_line = "—"
    if crm_stage:
        stage_line = f"{crm_stage[0]} · {CRM_STAGE_LABELS.get(crm_stage[1], crm_stage[1])}"
    text = (
        f"*Заявка #{oid}*\n\n"
        f"Статус заявки: `{status}`\n"
        f"CRM стадия: {stage_line}\n"
        f"Тип: {(payload.get('event_type') or '—')}\n"
        f"Город: {(payload.get('city') or '—')}\n"
        f"Дата: {(payload.get('event_date') or '—')}\n"
        f"Смена: {(payload.get('shift_time') or '—')}\n"
        f"Бюджет: {(payload.get('total_cost') or 0)} ₽"
    )
    kb_rows = _order_stage_buttons(oid, order_kind)
    back_kind = "kp" if order_kind == "cp_request" else "urgent"
    kb_rows.append([cb_btn("🔙 К воронке", f"admin_orders_funnel_{back_kind}")])
    kb_rows.append([cb_btn("🔙 CRM", "admin_hub_crm")])
    return {
        "notification": " ",
        "text": text[:3900],
        "format": "markdown",
        "attachments": inline_keyboard(kb_rows),
    }


def registered_menu_static_reply(max_uid: int, payload: str) -> dict[str, Any] | None:
    """Меню заказчика/исполнителя без активной SESSION (после clear_session)."""
    from funnel_db import (
        COOPERATION_MODE_PLATFORM,
        get_max_worker_cooperation_mode,
        is_max_visit_client_verified,
        is_max_visit_worker_verified,
        list_agency_visit_orders_for_user,
    )

    admin_payloads = {
        "admin_agency_hub",
        "admin_hub_ops",
        "admin_hub_hrm",
        "admin_hub_crm",
        "admin_hub_system",
        "admin_orders_funnel",
        "admin_orders_funnel_kp",
        "admin_orders_funnel_urgent",
        "admin_ops_shifts_active",
        "admin_ops_projects",
        "admin_ops_reports",
        "admin_hrm_join_recent",
        "admin_hrm_workers",
        "admin_hrm_worker_find",
        "admin_hrm_payments",
        "admin_hrm_payments_export",
        "admin_sys_admin_logs",
        "admin_sys_monitor",
        "admin_sys_subscriptions_expiring",
        "admin_phone_login_btn",
        "admin_identity_dupes",
    }
    if payload in admin_payloads or payload.startswith(
        (
            "admin_funnel__",
            "admin_order_detail_",
            "admin_order_stage_",
            "admin_ops_shift_detail_",
            "admin_ops_shift_assign_pick_",
            "admin_ops_shift_assign_do_",
            "admin_ops_shift_report_",
            "admin_ops_shift_risk_unconfirmed_",
            "admin_ops_shift_ping_unconfirmed_",
            "admin_ops_project_detail_",
            "admin_hrm_payment_",
            "admin_hrm_paystatus_",
            "admin_hrm_worker_detail_",
            "admin_sys_subs_mode_",
            "admin_sys_subs_company_",
            "admin_sys_subs_confirm_",
            "admin_sys_subs_act_",
        )
    ):
        if not _is_admin_max_uid(max_uid):
            return _admin_denied_reply(max_uid)
        counters = get_admin_hub_counters_max()
        if payload == "admin_agency_hub":
            return {
                "notification": " ",
                "text": (
                    "*Админ-меню MAX*\n\n"
                    "Хабы совпадают с Telegram: OPS, HRM, CRM, System.\n"
                    "Выберите раздел ниже.\n\n"
                    f"OPS: {int(counters.get('open_shifts', 0))} открытых смен\n"
                    f"На смене сейчас: {int(counters.get('checked_in_now', 0))} · "
                    f"на перерыве: {int(counters.get('on_break_now', 0))}\n"
                    f"HRM: {int(counters.get('workers_total', 0))} исполнителей · "
                    f"{int(counters.get('payments_pending', 0))} выплат pending\n"
                    f"CRM: {int(counters.get('crm_all', 0))} заявок в воронке"
                ),
                "format": "markdown",
                "attachments": visit_card.admin_agency_hub_keyboard(),
            }
        if payload == "admin_hub_ops":
            return {
                "notification": " ",
                "text": (
                    "*OPS (Операции)*\n\n"
                    "Контур операционного управления: смены, проекты, отчёты.\n\n"
                    f"Открытых смен: {int(counters.get('open_shifts', 0))}\n"
                    f"Проектов: {int(counters.get('projects_total', 0))}\n"
                    f"Сейчас на смене: {int(counters.get('checked_in_now', 0))}\n"
                    f"Сейчас на перерыве: {int(counters.get('on_break_now', 0))}"
                ),
                "format": "markdown",
                "attachments": visit_card.admin_hub_ops_keyboard(),
            }
        if payload == "admin_hub_hrm":
            return {
                "notification": " ",
                "text": (
                    "*HRM*\n\n"
                    "Управление анкетами исполнителей и контроль выплат.\n\n"
                    f"Исполнителей: {int(counters.get('workers_total', 0))}\n"
                    f"Выплат pending: {int(counters.get('payments_pending', 0))}"
                ),
                "format": "markdown",
                "attachments": visit_card.admin_hub_hrm_keyboard(),
            }
        if payload == "admin_hub_crm":
            return {
                "notification": " ",
                "text": (
                    "*CRM*\n\n"
                    "Воронка заказов в MAX: общий поток, KPI/KP и urgent.\n\n"
                    f"Всего: {int(counters.get('crm_all', 0))}\n"
                    f"KP: {int(counters.get('crm_kp', 0))}\n"
                    f"Urgent: {int(counters.get('crm_urgent', 0))}"
                ),
                "format": "markdown",
                "attachments": visit_card.admin_hub_crm_keyboard(),
            }
        if payload == "admin_hub_system":
            return {
                "notification": " ",
                "text": (
                    "*System*\n\n"
                    "Мониторинг и сервисные инструменты для поддержки.\n\n"
                    f"Открытых смен: {int(counters.get('open_shifts', 0))}\n"
                    f"Сейчас на смене: {int(counters.get('checked_in_now', 0))}\n"
                    f"Сейчас на перерыве: {int(counters.get('on_break_now', 0))}\n"
                    f"Pending выплат: {int(counters.get('payments_pending', 0))}\n"
                    f"CRM заявок: {int(counters.get('crm_all', 0))}"
                ),
                "format": "markdown",
                "attachments": visit_card.admin_hub_system_keyboard(),
            }
        if payload == "admin_orders_funnel":
            return _render_admin_funnel_message(kind="all", page=0, stage="all")
        if payload == "admin_orders_funnel_kp":
            return _render_admin_funnel_message(kind="kp", page=0, stage="all")
        if payload == "admin_orders_funnel_urgent":
            return _render_admin_funnel_message(kind="urgent", page=0, stage="all")
        if payload.startswith("admin_funnel__"):
            parsed_nav = _parse_funnel_nav_callback(payload)
            if not parsed_nav:
                return {
                    "notification": "Ошибка",
                    "text": "Некорректная страница воронки.",
                    "format": "markdown",
                    "attachments": visit_card.admin_hub_crm_keyboard(),
                }
            return _render_admin_funnel_message(kind=parsed_nav[0], page=parsed_nav[1], stage=parsed_nav[2])
        if payload.startswith("admin_order_detail_"):
            oid = _parse_order_detail_callback(payload)
            if not oid:
                return {
                    "notification": "Ошибка",
                    "text": "Некорректный идентификатор заявки.",
                    "format": "markdown",
                    "attachments": visit_card.admin_hub_crm_keyboard(),
                }
            return _render_admin_order_detail(oid)
        if payload.startswith("admin_order_stage_"):
            parsed_stage = _parse_order_stage_callback(payload)
            if not parsed_stage:
                return {
                    "notification": "Ошибка",
                    "text": "Некорректные данные кнопки стадии.",
                    "format": "markdown",
                    "attachments": visit_card.admin_hub_crm_keyboard(),
                }
            oid, stage = parsed_stage
            ok, msg = apply_visit_order_crm_stage_from_admin(oid, stage)
            if ok:
                log_admin_action_max(
                    int(max_uid),
                    "crm.stage.max",
                    "agency_visit_order",
                    oid,
                    (stage or "").strip(),
                )
            detail = _render_admin_order_detail(oid)
            detail["notification"] = "Обновлено" if ok else "Ошибка"
            if not ok:
                detail["text"] = (
                    f"{detail.get('text', '')}\n\n⚠️ {msg or 'Не удалось обновить стадию.'}"
                )[:3900]
            return detail
        if payload == "admin_sys_monitor":
            visit_stats = get_visitcard_stats()
            coop = get_worker_cooperation_mode_metrics()
            dup = get_users_phone_duplicates_metrics(limit=5)
            subs = get_company_subscription_metrics_max(days=7)
            return {
                "notification": " ",
                "text": (
                    "*Мониторинг*\n\n"
                    f"Заявки: {int(visit_stats.get('orders', 0))}\n"
                    f"Анкеты: {int(visit_stats.get('join', 0))}\n"
                    f"Вопросы: {int(visit_stats.get('questions', 0))}\n"
                    f"Агентские исполнители: {int(coop.get('agency_workers', 0))}\n"
                    f"Платформенные исполнители: {int(coop.get('platform_workers', 0))}\n"
                    f"Дубли телефонов users: {int(dup.get('duplicate_phones_total', 0))}\n\n"
                    "*Подписки компаний*\n"
                    f"Активные: {int(subs.get('active_total', 0))}\n"
                    f"Истекают 7 дней: {int(subs.get('expiring_soon', 0))}\n"
                    f"Истекли: {int(subs.get('expired_total', 0))}\n"
                    f"Без подписки: {int(subs.get('without_subscription', 0))}"
                ),
                "format": "markdown",
                "attachments": visit_card.admin_hub_system_keyboard(),
            }
        if payload == "admin_sys_subscriptions_expiring":
            mode = "expiring"
            rows = list_expiring_company_subscriptions_max(days=7, limit=30)
            text = _subs_list_text_max(mode, rows)
            return {
                "notification": " ",
                "text": text,
                "format": "markdown",
                "attachments": _subs_list_keyboard_max(mode, rows),
            }
        if payload.startswith("admin_sys_subs_mode_"):
            mode = payload.replace("admin_sys_subs_mode_", "", 1).strip().lower() or "expiring"
            rows = _subs_rows_by_mode_max(mode)
            return {
                "notification": " ",
                "text": _subs_list_text_max(mode, rows),
                "format": "markdown",
                "attachments": _subs_list_keyboard_max(mode, rows),
            }
        if payload.startswith("admin_sys_subs_company_"):
            parsed = _parse_subs_company_cb_max(payload)
            if not parsed:
                return {
                    "notification": "Ошибка",
                    "text": "Некорректные данные компании.",
                    "format": "markdown",
                    "attachments": visit_card.admin_hub_system_keyboard(),
                }
            cid, mode = parsed
            return {
                "notification": " ",
                "text": _subs_company_detail_text_max(cid),
                "format": "markdown",
                "attachments": _subs_company_detail_keyboard_max(cid, mode),
            }
        if payload.startswith("admin_sys_subs_confirm_"):
            parsed = _parse_subs_confirm_cb_max(payload)
            if not parsed:
                return {
                    "notification": "Ошибка",
                    "text": "Некорректные данные подтверждения.",
                    "format": "markdown",
                    "attachments": visit_card.admin_hub_system_keyboard(),
                }
            cid, action, mode = parsed
            return {
                "notification": "Подтвердите",
                "text": _subs_confirm_text_max(cid, action),
                "format": "markdown",
                "attachments": _subs_confirm_keyboard_max(cid, action, mode),
            }
        if payload.startswith("admin_sys_subs_act_"):
            parsed = _parse_subs_action_cb_max(payload)
            if not parsed:
                return {
                    "notification": "Ошибка",
                    "text": "Некорректные данные действия.",
                    "format": "markdown",
                    "attachments": visit_card.admin_hub_system_keyboard(),
                }
            cid, action, mode = parsed
            ok = False
            if action == "extend":
                ok = admin_extend_company_subscription_days_max(cid, days=30)
                if ok:
                    log_admin_action_max(int(max_uid), "subscription_extend_30d", "company_subscription", cid, "via_max_admin")
            elif action == "grace":
                ok = admin_set_company_subscription_grace_max(cid, days=7)
                if ok:
                    log_admin_action_max(int(max_uid), "subscription_grace_7d", "company_subscription", cid, "via_max_admin")
            if not ok:
                return {
                    "notification": "Ошибка",
                    "text": "Не удалось обновить подписку компании.",
                    "format": "markdown",
                    "attachments": _subs_company_detail_keyboard_max(cid, mode),
                }
            return {
                "notification": "Обновлено",
                "text": _subs_company_detail_text_max(cid),
                "format": "markdown",
                "attachments": _subs_company_detail_keyboard_max(cid, mode),
            }
        if payload == "admin_sys_admin_logs":
            rows = list_admin_logs_max(limit=30)
            if not rows:
                text = "*Лог админ-действий*\n\nЗаписей пока нет."
            else:
                lines = ["*Лог админ-действий (последние 30)*", ""]
                for row in rows:
                    lines.append(
                        "• "
                        f"{(row.get('created_at') or '—')} · "
                        f"uid={int(row.get('admin_user_id') or 0)} · "
                        f"{(row.get('action') or '—')} · "
                        f"{(row.get('entity_type') or '—')}:{(row.get('entity_id') or '—')}"
                    )
                text = "\n".join(lines)[:3900]
            return {
                "notification": " ",
                "text": text,
                "format": "markdown",
                "attachments": visit_card.admin_hub_system_keyboard(),
            }
        if payload == "admin_phone_login_btn":
            rows = list_visit_phone_login_log(25)
            if not rows:
                text = "*Вход по телефону*\n\nЗаписей пока нет."
            else:
                lines = ["*Вход по телефону (MAX/TG)*", ""]
                for src, uid, un, role, phone, outcome, created_at in rows:
                    who = f"@{un}" if un else str(uid)
                    out_ru = OUTCOME_LABELS_RU.get(str(outcome), str(outcome))
                    lines.append(f"• {src} · {who} · {role} · {phone} · {out_ru} · {created_at}")
                text = "\n".join(lines)[:3900]
            return {
                "notification": " ",
                "text": text,
                "format": "markdown",
                "attachments": visit_card.admin_hub_system_keyboard(),
            }
        if payload == "admin_identity_dupes":
            dup = get_users_phone_duplicates_metrics(limit=10)
            sample = dup.get("sample") or []
            lines = [
                "*Дубли по users.phone*",
                "",
                f"Номеров с дублями: {int(dup.get('duplicate_phones_total', 0))}",
                f"Строк в дублях: {int(dup.get('duplicate_rows_total', 0))}",
            ]
            if sample:
                lines.append("")
                lines.append("Примеры:")
                for row in sample[:10]:
                    lines.append(
                        f"• {row.get('phone_norm')} · {row.get('cnt')} шт · tg_id={row.get('tg_ids')}"
                    )
            return {
                "notification": " ",
                "text": "\n".join(lines)[:3900],
                "format": "markdown",
                "attachments": visit_card.admin_hub_system_keyboard(),
            }
        if payload == "admin_hrm_join_recent":
            rows = list_visit_rows("join", limit=12)
            if not rows:
                text = "*HRM: последние анкеты*\n\nПока нет заявок."
            else:
                lines = ["*HRM: последние анкеты*", ""]
                for row in rows:
                    payload_row = row.get("payload")
                    data = {}
                    if isinstance(payload_row, str):
                        try:
                            data = json.loads(payload_row)
                        except Exception:
                            data = {}
                    elif isinstance(payload_row, dict):
                        data = payload_row
                    full_name = (data.get("full_name") or "—") if isinstance(data, dict) else "—"
                    position = (data.get("position") or "—") if isinstance(data, dict) else "—"
                    lines.append(f"• #{row.get('id')} · {full_name} · {position}")
                text = "\n".join(lines)[:3900]
            return {
                "notification": " ",
                "text": text,
                "format": "markdown",
                "attachments": visit_card.admin_hub_hrm_keyboard(),
            }
        if payload == "admin_hrm_worker_find":
            clear_session(max_uid)
            SESSIONS[max_uid] = {"flow": "admin_hrm_find_worker", "step": "query", "data": {}}
            return {
                "notification": "Поиск",
                "text": (
                    "*Найти исполнителя*\n\n"
                    "Введите ФИО, телефон или `user_id` исполнителя.\n\n"
                    "Пример: `Иванов` или `7968...`."
                ),
                "format": "markdown",
                "attachments": visit_card.admin_hub_hrm_keyboard(),
            }
        if payload.startswith("admin_hrm_worker_detail_"):
            wid = _parse_worker_detail_callback(payload) or 0
            worker = get_worker_admin_max(wid)
            if not worker:
                return {
                    "notification": "Не найдено",
                    "text": "Исполнитель не найден.",
                    "format": "markdown",
                    "attachments": visit_card.admin_hub_hrm_keyboard(),
                }
            stats = get_worker_assignment_stats_max(wid)
            pays = list_worker_payments_for_worker_max(wid, limit=5)
            lines = [
                f"*Исполнитель {int(worker.get('user_id') or 0)}*",
                "",
                f"ФИО: {(worker.get('full_name') or '—')}",
                f"Телефон: {(worker.get('phone') or '—')}",
                f"Профессия: {(worker.get('profession') or '—')}",
                f"Статус: `{(worker.get('status') or 'new')}`",
                f"Режим: {(worker.get('cooperation_mode') or 'agency')}",
                f"Рейтинг: {float(worker.get('rating') or 0):.2f}",
                f"Назначений: {int(stats.get('assignments_total') or 0)}",
                f"Открытых задач: {int(stats.get('open_tasks') or 0)}",
            ]
            if pays:
                lines.append("")
                lines.append("*Последние выплаты:*")
                for p in pays[:5]:
                    st_pay = str(p.get("status") or "").strip().lower()
                    lines.append(
                        "• "
                        f"#{int(p.get('id') or 0)} · "
                        f"{float(p.get('amount_rub') or 0):.2f} ₽ · "
                        f"{PAYMENT_STATUS_LABELS_RU.get(st_pay, st_pay or '—')} · "
                        f"{(p.get('title') or '—')}"
                    )
            return {
                "notification": " ",
                "text": "\n".join(lines)[:3900],
                "format": "markdown",
                "attachments": inline_keyboard(
                    [
                        [cb_btn("🔙 Поиск исполнителя", "admin_hrm_worker_find")],
                        [cb_btn("🔙 HRM", "admin_hub_hrm")],
                    ]
                ),
            }
        if payload == "admin_hrm_workers":
            rows = list_workers_admin_max(limit=25)
            if not rows:
                text = "*HRM: исполнители*\n\nЗаписей пока нет."
            else:
                lines = ["*HRM: исполнители (последние 25)*", ""]
                for row in rows:
                    lines.append(
                        "• "
                        f"{(row.get('full_name') or '—')} ({int(row.get('user_id') or 0)})"
                        f" · {(row.get('profession') or '—')}"
                        f" · `{(row.get('status') or 'new')}`"
                        f" · mode={(row.get('cooperation_mode') or 'agency')}"
                    )
                text = "\n".join(lines)[:3900]
            return {
                "notification": " ",
                "text": text,
                "format": "markdown",
                "attachments": visit_card.admin_hub_hrm_keyboard(),
            }
        if payload.startswith("admin_hrm_payment_"):
            m = re.match(r"^admin_hrm_payment_(\d+)$", payload)
            pid = int(m.group(1)) if m else 0
            row = get_worker_payment_admin_max(pid)
            if not row:
                return {
                    "notification": "Не найдено",
                    "text": "Выплата не найдена.",
                    "format": "markdown",
                    "attachments": visit_card.admin_hub_hrm_keyboard(),
                }
            text = (
                f"*Выплата #{int(row.get('id') or 0)}*\n\n"
                f"Исполнитель: {(row.get('worker_name') or '—')} ({int(row.get('worker_tg_id') or 0)})\n"
                f"Сумма: {float(row.get('amount_rub') or 0):.2f} {row.get('currency') or 'RUB'}\n"
                f"Статус: {PAYMENT_STATUS_LABELS_RU.get(str(row.get('status') or ''), str(row.get('status') or '—'))}\n"
                f"Основание: {(row.get('title') or '—')}\n"
                f"Период: {(row.get('period_label') or '—')}\n"
                f"Смена: {(row.get('shift_id') or '—')}\n"
                f"Создано: {(row.get('created_at') or '—')}\n"
                f"Оплачено: {(row.get('paid_at') or '—')}"
            )
            notes = (row.get("notes") or "").strip()
            if notes:
                text += f"\n\nКомментарий:\n{notes}"
            return {
                "notification": " ",
                "text": text[:3900],
                "format": "markdown",
                "attachments": inline_keyboard(
                    [
                        [
                            cb_btn("⏳ Ожидает", f"admin_hrm_paystatus_{pid}_pending"),
                            cb_btn("✅ Согласована", f"admin_hrm_paystatus_{pid}_approved"),
                        ],
                        [
                            cb_btn("💵 Выплачена", f"admin_hrm_paystatus_{pid}_paid"),
                            cb_btn("🚫 Отменена", f"admin_hrm_paystatus_{pid}_cancelled"),
                        ],
                        [cb_btn("🔙 К выплатам", "admin_hrm_payments")],
                        [cb_btn("🔙 HRM", "admin_hub_hrm")],
                    ]
                ),
            }
        if payload.startswith("admin_hrm_paystatus_"):
            parsed_payment = _parse_payment_status_callback(payload)
            if not parsed_payment:
                return {
                    "notification": "Ошибка",
                    "text": "Некорректные данные статуса выплаты.",
                    "format": "markdown",
                    "attachments": visit_card.admin_hub_hrm_keyboard(),
                }
            pid, new_status = parsed_payment
            ok, msg = update_worker_payment_status_max(pid, new_status)
            if ok:
                log_admin_action_max(
                    int(max_uid),
                    "worker_payment.status.max",
                    "worker_payment",
                    pid,
                    new_status,
                )
            detail = registered_menu_static_reply(max_uid, f"admin_hrm_payment_{pid}") or {
                "notification": " ",
                "text": "*HRM выплаты*",
                "format": "markdown",
                "attachments": visit_card.admin_hub_hrm_keyboard(),
            }
            detail["notification"] = "Обновлено" if ok else "Ошибка"
            if not ok:
                detail["text"] = (str(detail.get("text") or "") + f"\n\n⚠️ {msg}")[:3900]
            return detail
        if payload == "admin_hrm_payments":
            rows = list_worker_payments_recent_max(limit=20)
            if not rows:
                return {
                    "notification": "Пусто",
                    "text": "*HRM выплаты*\n\nЗаписей выплат пока нет.",
                    "format": "markdown",
                    "attachments": visit_card.admin_hub_hrm_keyboard(),
                }
            lines = ["*HRM выплаты (последние 20)*", ""]
            kb_rows: list[list[dict]] = []
            for row in rows:
                pid = int(row.get("id") or 0)
                title = (row.get("title") or "").strip() or "Выплата"
                worker = (row.get("worker_name") or "").strip() or str(int(row.get("worker_tg_id") or 0))
                amount = float(row.get("amount_rub") or 0)
                st = (row.get("status") or "—").strip()
                st_ru = PAYMENT_STATUS_LABELS_RU.get(st, st)
                lines.append(f"• #{pid} · {worker} · {amount:.2f} ₽ · {st_ru} · {title}")
                kb_rows.append([cb_btn(f"💳 Выплата #{pid}", f"admin_hrm_payment_{pid}")])
            return {
                "notification": " ",
                "text": "\n".join(lines)[:3900],
                "format": "markdown",
                "attachments": inline_keyboard(
                    kb_rows + [[cb_btn("🔙 HRM", "admin_hub_hrm")]]
                ),
            }
        if payload == "admin_hrm_payments_export":
            rows = list_worker_payments_recent_max(limit=120)
            if not rows:
                return {
                    "notification": "Пусто",
                    "text": "*CSV выплат*\n\nНет данных для экспорта.",
                    "format": "markdown",
                    "attachments": visit_card.admin_hub_hrm_keyboard(),
                }
            header = "id,worker_tg_id,worker_name,amount_rub,currency,status,title,shift_id,created_at,paid_at"
            csv_lines = [header]
            for row in rows:
                def _cell(v: object) -> str:
                    s = str(v or "").replace('"', '""')
                    return f"\"{s}\""
                csv_lines.append(
                    ",".join(
                        [
                            _cell(row.get("id")),
                            _cell(row.get("worker_tg_id")),
                            _cell(row.get("worker_name")),
                            _cell(row.get("amount_rub")),
                            _cell(row.get("currency")),
                            _cell(row.get("status")),
                            _cell(row.get("title")),
                            _cell(row.get("shift_id")),
                            _cell(row.get("created_at")),
                            _cell(row.get("paid_at")),
                        ]
                    )
                )
            body = "\n".join(csv_lines)
            max_len = 3600
            if len(body) > max_len:
                body = body[:max_len] + "\n...truncated..."
            return {
                "notification": "Готово",
                "text": f"*CSV выплат (preview)*\n\n```csv\n{body}\n```",
                "format": "markdown",
                "attachments": visit_card.admin_hub_hrm_keyboard(),
            }
        if payload.startswith("admin_ops_shift_detail_"):
            m = re.match(r"^admin_ops_shift_detail_(\d+)$", payload)
            sid = int(m.group(1)) if m else 0
            row = get_shift_admin_max(sid)
            if not row:
                return {
                    "notification": "Не найдено",
                    "text": "Смена не найдена.",
                    "format": "markdown",
                    "attachments": visit_card.admin_hub_ops_keyboard(),
                }
            assigns = list_shift_assignments_for_shift_max(sid, limit=120)
            status_counts = {
                "assigned": 0,
                "confirmed": 0,
                "checked_in": 0,
                "checked_out": 0,
                "cancelled": 0,
                "other": 0,
            }
            for a in assigns:
                st = str(a.get("status") or "").strip().lower()
                if st in status_counts:
                    status_counts[st] += 1
                else:
                    status_counts["other"] += 1
            risk_lines = _ops_shift_risk_lines_max(row, status_counts)
            text = (
                f"*Смена #{int(row.get('id') or 0)}*\n\n"
                f"Проект: {(row.get('project_name') or '—')}\n"
                f"Дата: {(row.get('shift_date') or '—')}\n"
                f"Время: {(row.get('start_time') or '—')} - {(row.get('end_time') or '—')}\n"
                f"Локация: {(row.get('location') or '—')}\n"
                f"Ставка: {int(row.get('rate') or 0)} ₽/ч\n"
                f"Нужно: {int(row.get('workers_needed') or 0)}\n"
                f"Назначено: {int(row.get('assignments_total') or 0)}\n"
                f"Статус: `{row.get('status') or '—'}`\n"
                f"Статусы: assigned {status_counts['assigned']} · "
                f"confirmed {status_counts['confirmed']} · "
                f"checked_in {status_counts['checked_in']} · "
                f"checked_out {status_counts['checked_out']} · "
                f"cancelled {status_counts['cancelled']}"
                + (f" · other {status_counts['other']}" if status_counts["other"] else "")
                + "\n\n"
                + (
                    "🚨 Риски:\n" + "\n".join(risk_lines) + "\n\n"
                    if risk_lines
                    else ""
                )
                + "Исполнители:\n"
                + _format_assignment_compact_lines_max(assigns, limit=12)
            )
            return {
                "notification": " ",
                "text": text[:3900],
                "format": "markdown",
                "attachments": inline_keyboard(
                    [
                        [cb_btn("👷 Назначить исполнителя", f"admin_ops_shift_assign_pick_{sid}")],
                        [cb_btn("🧾 Отчёт по смене", f"admin_ops_shift_report_{sid}")],
                        [cb_btn("📣 Неподтверждённые", f"admin_ops_shift_risk_unconfirmed_{sid}")],
                        [cb_btn("📮 Пинг в админ-канал", f"admin_ops_shift_ping_unconfirmed_{sid}")],
                        [cb_btn("🔙 К сменам", "admin_ops_shifts_active")],
                        [cb_btn("🔙 OPS", "admin_hub_ops")],
                    ]
                ),
            }
        if payload.startswith("admin_ops_shift_risk_unconfirmed_"):
            m = re.match(r"^admin_ops_shift_risk_unconfirmed_(\d+)$", payload)
            sid = int(m.group(1)) if m else 0
            row = get_shift_admin_max(sid)
            if not row:
                return {
                    "notification": "Не найдено",
                    "text": "Смена не найдена.",
                    "format": "markdown",
                    "attachments": visit_card.admin_hub_ops_keyboard(),
                }
            assigns = list_shift_assignments_for_shift_max(sid, limit=120)
            unconfirmed = [a for a in assigns if str(a.get("status") or "").strip().lower() == "assigned"]
            if not unconfirmed:
                text = f"*Смена #{sid}*\n\nНеподтверждённых назначений сейчас нет."
            else:
                lines = [f"*Смена #{sid} · неподтверждённые*", ""]
                for a in unconfirmed[:30]:
                    lines.append(f"• {(a.get('worker_name') or a.get('worker_tg_id') or '—')} ({a.get('worker_tg_id')})")
                text = "\n".join(lines)
            return {
                "notification": " ",
                "text": text[:3900],
                "format": "markdown",
                "attachments": inline_keyboard(
                    [
                        [cb_btn("👷 Назначить исполнителя", f"admin_ops_shift_assign_pick_{sid}")],
                        [cb_btn("🔙 К смене", f"admin_ops_shift_detail_{sid}")],
                    ]
                ),
            }
        if payload.startswith("admin_ops_shift_ping_unconfirmed_"):
            m = re.match(r"^admin_ops_shift_ping_unconfirmed_(\d+)$", payload)
            sid = int(m.group(1)) if m else 0
            row = get_shift_admin_max(sid)
            if not row:
                return {
                    "notification": "Не найдено",
                    "text": "Смена не найдена.",
                    "format": "markdown",
                    "attachments": visit_card.admin_hub_ops_keyboard(),
                }
            assigns = list_shift_assignments_for_shift_max(sid, limit=120)
            unconfirmed = [a for a in assigns if str(a.get("status") or "").strip().lower() == "assigned"]
            if not unconfirmed:
                return {
                    "notification": "Нет рисков",
                    "text": "Неподтверждённых назначений нет — пинг не требуется.",
                    "format": "markdown",
                    "attachments": inline_keyboard([[cb_btn("🔙 К смене", f"admin_ops_shift_detail_{sid}")]]),
                }
            in_window, reason = _is_unconfirmed_ping_window_max(row)
            if not in_window:
                return {
                    "notification": "Вне окна",
                    "text": (
                        f"*Смена #{sid}*\n\n"
                        "Пинг неподтверждённых сейчас не отправлен.\n\n"
                        f"{reason}"
                    ),
                    "format": "markdown",
                    "attachments": inline_keyboard([[cb_btn("🔙 К смене", f"admin_ops_shift_detail_{sid}")]]),
                }
            plain_lines = [
                f"MAX OPS: смена #{sid}",
                f"Проект: {(row.get('project_name') or '—')}",
                f"Дата: {(row.get('shift_date') or '—')} {(row.get('start_time') or '—')}-{(row.get('end_time') or '—')}",
                "",
                "Неподтверждённые исполнители (assigned):",
            ]
            for a in unconfirmed[:40]:
                plain_lines.append(f"- {(a.get('worker_name') or a.get('worker_tg_id') or '—')} ({a.get('worker_tg_id')})")
            _schedule_notify(
                f"[MAX] Пинг неподтверждённых · смена #{sid}",
                "\n".join(plain_lines),
            )
            log_admin_action_max(int(max_uid), "risk_ping_unconfirmed", "shift", sid, f"count={len(unconfirmed)};via_max")
            return {
                "notification": "Отправлено",
                "text": (
                    f"*Смена #{sid}*\n\n"
                    f"Отправил пинг в админ-канал по неподтверждённым назначениям: {len(unconfirmed)}."
                ),
                "format": "markdown",
                "attachments": inline_keyboard([[cb_btn("🔙 К смене", f"admin_ops_shift_detail_{sid}")]]),
            }
        if payload.startswith("admin_ops_shift_assign_pick_"):
            m = re.match(r"^admin_ops_shift_assign_pick_(\d+)$", payload)
            sid = int(m.group(1)) if m else 0
            row = get_shift_admin_max(sid)
            if not row:
                return {
                    "notification": "Не найдено",
                    "text": "Смена не найдена.",
                    "format": "markdown",
                    "attachments": visit_card.admin_hub_ops_keyboard(),
                }
            workers = list_assignable_workers_for_shift_max(sid, limit=20)
            if not workers:
                return {
                    "notification": "Пусто",
                    "text": (
                        f"*Назначение на смену #{sid}*\n\n"
                        "Нет доступных исполнителей (approved/agency) или все уже назначены."
                    ),
                    "format": "markdown",
                    "attachments": inline_keyboard(
                        [
                            [cb_btn("🔙 К смене", f"admin_ops_shift_detail_{sid}")],
                            [cb_btn("🔙 OPS", "admin_hub_ops")],
                        ]
                    ),
                }
            lines = [f"*Назначение на смену #{sid}*", ""]
            kb_rows: list[list[dict]] = []
            for w in workers:
                wid = int(w.get("user_id") or 0)
                fio = (w.get("full_name") or "—").strip()
                prof = (w.get("profession") or "—").strip()
                lines.append(f"• {fio} ({wid}) · {prof}")
                kb_rows.append([cb_btn(f"➕ {fio[:40]}", f"admin_ops_shift_assign_do_{sid}_{wid}")])
            kb_rows.append([cb_btn("🔙 К смене", f"admin_ops_shift_detail_{sid}")])
            return {
                "notification": " ",
                "text": "\n".join(lines)[:3900],
                "format": "markdown",
                "attachments": inline_keyboard(kb_rows),
            }
        if payload.startswith("admin_ops_shift_assign_do_"):
            m = re.match(r"^admin_ops_shift_assign_do_(\d+)_(\d+)$", payload)
            sid = int(m.group(1)) if m else 0
            wid = int(m.group(2)) if m else 0
            ok, msg = assign_worker_to_shift_max(sid, wid)
            if ok:
                log_admin_action_max(int(max_uid), "assign_worker_to_shift", "shift", sid, f"worker={wid};via_max")
            detail = registered_menu_static_reply(max_uid, f"admin_ops_shift_detail_{sid}") or {
                "notification": "Ошибка",
                "text": "Не удалось открыть карточку смены.",
                "format": "markdown",
                "attachments": visit_card.admin_hub_ops_keyboard(),
            }
            detail["notification"] = "Обновлено" if ok else "Ошибка"
            detail["text"] = f"{detail.get('text', '')}\n\n{'✅' if ok else '⚠️'} {msg}".strip()[:3900]
            return detail
        if payload.startswith("admin_ops_shift_report_"):
            m = re.match(r"^admin_ops_shift_report_(\d+)$", payload)
            sid = int(m.group(1)) if m else 0
            row = get_shift_admin_max(sid)
            if not row:
                return {
                    "notification": "Не найдено",
                    "text": "Смена не найдена.",
                    "format": "markdown",
                    "attachments": visit_card.admin_hub_ops_keyboard(),
                }
            assigns = list_shift_assignments_for_shift_max(sid, limit=120)
            lines = [
                f"*Отчёт по смене #{sid}*",
                "",
                f"Проект: {(row.get('project_name') or '—')}",
                f"Дата: {(row.get('shift_date') or '—')}",
                f"Время: {(row.get('start_time') or '—')} - {(row.get('end_time') or '—')}",
                "",
            ]
            if not assigns:
                lines.append("Назначений пока нет.")
            else:
                lines.append(f"Назначений: {len(assigns)}")
                lines.append("")
                for a in assigns:
                    st = str(a.get("status") or "—")
                    lines.append(
                        f"• {(a.get('worker_name') or a.get('worker_tg_id') or '—')} · `{st}`\n"
                        f"  чек-ин: {a.get('checkin_time') or '—'} · "
                        f"чекаут: {a.get('checkout_time') or '—'} · "
                        f"мин: {int(a.get('worked_minutes') or 0)}"
                    )
            return {
                "notification": " ",
                "text": "\n".join(lines)[:3900],
                "format": "markdown",
                "attachments": inline_keyboard(
                    [
                        [cb_btn("🔙 К смене", f"admin_ops_shift_detail_{sid}")],
                        [cb_btn("🔙 К сменам", "admin_ops_shifts_active")],
                    ]
                ),
            }
        if payload.startswith("admin_ops_project_detail_"):
            m = re.match(r"^admin_ops_project_detail_(\d+)$", payload)
            pid = int(m.group(1)) if m else 0
            row = get_project_admin_max(pid)
            if not row:
                return {
                    "notification": "Не найдено",
                    "text": "Проект не найден.",
                    "format": "markdown",
                    "attachments": visit_card.admin_hub_ops_keyboard(),
                }
            text = (
                f"*Проект #{int(row.get('id') or 0)}*\n\n"
                f"Название: {(row.get('name') or '—')}\n"
                f"Компания: {(row.get('company_name') or '—')} (ID {int(row.get('company_id') or 0)})\n"
                f"Всего смен: {int(row.get('shifts_total') or 0)}\n"
                f"Открытых смен: {int(row.get('shifts_open') or 0)}"
            )
            return {
                "notification": " ",
                "text": text[:3900],
                "format": "markdown",
                "attachments": inline_keyboard(
                    [
                        [cb_btn("🔙 К проектам", "admin_ops_projects")],
                        [cb_btn("🔙 OPS", "admin_hub_ops")],
                    ]
                ),
            }
        if payload == "admin_ops_shifts_active":
            rows = list_open_shifts_admin_max(limit=20)
            if not rows:
                text = "*OPS: активные смены*\n\nПока нет открытых смен."
            else:
                lines = ["*OPS: активные смены*", ""]
                kb_rows: list[list[dict]] = []
                for row in rows:
                    sid = int(row.get("id") or 0)
                    date = (row.get("shift_date") or "—").strip()
                    project = (row.get("project_name") or "—").strip()
                    time_range = f"{(row.get('start_time') or '—')} - {(row.get('end_time') or '—')}"
                    status = (row.get("status") or "—").strip()
                    need = int(row.get("workers_needed") or 0)
                    assigned = int(row.get("assignments_total") or 0)
                    lines.append(
                        f"• #{sid} · {date} · {project} · {time_range} · `{status}`\n"
                        f"  люди: {assigned}/{need}"
                    )
                    kb_rows.append([cb_btn(f"📅 Смена #{sid}", f"admin_ops_shift_detail_{sid}")])
                text = "\n".join(lines)[:3900]
                return {
                    "notification": " ",
                    "text": text,
                    "format": "markdown",
                    "attachments": inline_keyboard(
                        kb_rows + [[cb_btn("🔙 OPS", "admin_hub_ops")]]
                    ),
                }
            return {
                "notification": " ",
                "text": text,
                "format": "markdown",
                "attachments": visit_card.admin_hub_ops_keyboard(),
            }
        if payload == "admin_ops_projects":
            rows = list_projects_admin_max(limit=20)
            if not rows:
                return {
                    "notification": "Пусто",
                    "text": "*OPS: проекты*\n\nПроекты не найдены.",
                    "format": "markdown",
                    "attachments": visit_card.admin_hub_ops_keyboard(),
                }
            lines = ["*OPS: проекты*", ""]
            kb_rows = []
            for row in rows:
                pid = int(row.get("id") or 0)
                title = (row.get("name") or "—").strip()
                company = (row.get("company_name") or "—").strip()
                lines.append(f"• #{pid} · {title} · {company}")
                kb_rows.append([cb_btn(f"📦 Проект #{pid}", f"admin_ops_project_detail_{pid}")])
            return {
                "notification": " ",
                "text": "\n".join(lines)[:3900],
                "format": "markdown",
                "attachments": inline_keyboard(
                    kb_rows + [[cb_btn("🔙 OPS", "admin_hub_ops")]]
                ),
            }
        if payload == "admin_ops_reports":
            rows = list_shift_assignments_recent_max(limit=25)
            if not rows:
                text = "*OPS: отчёты / назначения*\n\nНазначений пока нет."
            else:
                lines = ["*OPS: последние назначения на смены*", ""]
                for row in rows:
                    lines.append(
                        "• "
                        f"#{int(row.get('id') or 0)} · "
                        f"смена {int(row.get('shift_id') or 0)} · "
                        f"{(row.get('worker_name') or row.get('worker_tg_id') or '—')} · "
                        f"`{(row.get('status') or '—')}`"
                    )
                text = "\n".join(lines)[:3900]
            return {
                "notification": " ",
                "text": text,
                "format": "markdown",
                "attachments": visit_card.admin_hub_ops_keyboard(),
            }

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
                "Раздел синхронизируется с веб-кабинетом Promostaff.\n"
                "Пока откройте «Кабинет на сайте» в этом меню — там основной рабочий контур."
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
            "text": (
                "*Настройки*\n\n"
                "Раздел в разработке. Сейчас изменения профиля и уведомлений делаются через кабинет и менеджера."
            ),
            "format": "markdown",
            "attachments": visit_card.client_registered_main_menu_keyboard(),
        }

    if payload in ("client_reg_web", "open_web_cabinet", "client_cabinet"):
        cl_ok = bool(is_max_visit_client_verified(max_uid))
        wk_ok = bool(is_max_visit_worker_verified(max_uid))
        if not cl_ok and not wk_ok:
            return {
                "notification": "Нужна верификация",
                "text": "Кабинет на сайте доступен после верификации профиля.",
                "format": "markdown",
                "attachments": visit_card.main_menu_keyboard(),
            }
        from cabinet_web_login_token import build_cabinet_web_login_url

        url, err = build_cabinet_web_login_url(max_uid)
        if not url:
            base_kb = (
                visit_card.client_registered_main_menu_keyboard()
                if cl_ok
                else visit_card.worker_registered_main_menu_keyboard()
            )
            retry_kb = inline_keyboard(
                [
                    [cb_btn("🔁 Повторить вход в кабинет", "open_web_cabinet")],
                    [cb_btn("📞 Связаться с менеджером", "contact_manager")],
                    [cb_btn("🏠 Меню визитки", "visit_public_menu")],
                ]
            )
            return {
                "notification": "Ошибка",
                "text": (
                    "*Кабинет на сайте*\n\n"
                    f"{(err or 'Не удалось подготовить ссылку. Попробуйте позже.')}\n\n"
                    "Можно повторить попытку кнопкой ниже."
                ),
                "format": "markdown",
                "attachments": retry_kb if err else base_kb,
            }
        return {
            "notification": " ",
            "text": (
                "*Кабинет на сайте*\n\n"
                "Откройте кабинет в браузере. Ссылка одноразовая и действует около 15 минут."
            ),
            "format": "markdown",
            "attachments": inline_keyboard(
                [
                    [link_btn("🌐 Открыть кабинет", url)],
                    [cb_btn("🏠 Меню визитки", "visit_public_menu")],
                ]
            ),
        }

    worker_payload_roots = {
        "worker_reg_profile",
        "worker_reg_shifts",
        "worker_reg_payments",
        "worker_reg_beacon",
    }
    if payload in worker_payload_roots or payload.startswith(
        (
            "worker_shift_",
            "worker_break_menu_",
            "worker_break_start_",
            "worker_break_stop_",
            "worker_beacon_",
        )
    ):
        if (
            has_max_active_executor_profile(max_uid)
            and get_max_worker_cooperation_mode(max_uid) == COOPERATION_MODE_PLATFORM
        ):
            global _PLATFORM_GATE_BLOCKS_TOTAL
            _PLATFORM_GATE_BLOCKS_TOTAL += 1
            _PLATFORM_GATE_BLOCKS_BY_USER[int(max_uid)] = int(
                _PLATFORM_GATE_BLOCKS_BY_USER.get(int(max_uid), 0)
            ) + 1
            return {
                "notification": "Платформенный контур",
                "text": (
                    "*Профиль исполнителя подтверждён.*\n\n"
                    "Для аккаунта включён платформенный режим: агентские смены в MAX не показываются по умолчанию.\n"
                    "Используйте кабинет на сайте или обратитесь к менеджеру для переключения режима."
                ),
                "format": "markdown",
                "attachments": visit_card.main_menu_keyboard(),
            }
        if not is_max_visit_worker_verified(max_uid):
            return {
                "notification": "Сначала регистрация и верификация",
                "text": (
                    "Сначала пройдите регистрацию исполнителя и дождитесь подтверждения заявки администратором."
                ),
                "format": "markdown",
                "attachments": visit_card.main_menu_keyboard(),
            }

        worker_tg_id = resolve_tg_id_for_max_user(int(max_uid))
        if payload == "worker_reg_profile":
            w = get_worker_admin_max(worker_tg_id)
            stats = get_worker_assignment_stats_max(worker_tg_id)
            if not w:
                text = "*Мои данные*\n\nПрофиль исполнителя пока не найден."
            else:
                text = (
                    "*Мои данные*\n\n"
                    f"ФИО: {w.get('full_name') or '—'}\n"
                    f"Телефон: {w.get('phone') or '—'}\n"
                    f"Профессия: {w.get('profession') or '—'}\n"
                    f"Статус: {w.get('status') or '—'}\n"
                    f"Режим: {w.get('cooperation_mode') or 'agency'}\n"
                    f"Смен всего: {int(stats.get('assignments_total', 0))}\n"
                    f"Открытых задач: {int(stats.get('open_tasks', 0))}"
                )
            return {
                "notification": " ",
                "text": text,
                "format": "markdown",
                "attachments": visit_card.worker_registered_main_menu_keyboard(),
            }
        if payload == "worker_reg_payments":
            rows = list_worker_payments_for_worker_max(worker_tg_id, limit=20)
            if not rows:
                text = "*Мои выплаты*\n\nВыплат пока нет."
            else:
                lines = ["*Мои выплаты*", ""]
                for row in rows[:20]:
                    st = str(row.get("status") or "")
                    lines.append(
                        f"• #{int(row.get('id') or 0)} · {float(row.get('amount_rub') or 0):.2f} "
                        f"{row.get('currency') or 'RUB'} · "
                        f"{PAYMENT_STATUS_LABELS_RU.get(st, st or '—')}\n"
                        f"  {(row.get('title') or 'Выплата')} · {row.get('created_at') or '—'}"
                    )
                text = "\n".join(lines)[:3900]
            return {
                "notification": " ",
                "text": text,
                "format": "markdown",
                "attachments": visit_card.worker_registered_main_menu_keyboard(),
            }
        if payload == "worker_reg_beacon":
            st = get_worker_beacon_state_max(worker_tg_id)
            active = bool(st.get("is_active"))
            text = (
                "*Маяк*\n\n"
                f"Статус: {'🟢 Включен' if active else '⚪ Выключен'}\n"
                f"Включен с: {st.get('enabled_at') or '—'}\n"
                f"До: {st.get('expires_at') or '—'}"
            )
            kb_rows = [
                [cb_btn("🟢 Включить на 24ч", "worker_beacon_on")],
                [cb_btn("⚪ Выключить", "worker_beacon_off")],
                [cb_btn("🔙 Меню исполнителя", "main_menu")],
            ]
            return {
                "notification": " ",
                "text": text,
                "format": "markdown",
                "attachments": inline_keyboard(kb_rows),
            }
        if payload == "worker_beacon_on":
            ok = enable_worker_beacon_max(worker_tg_id, hours=24)
            if not ok:
                return {
                    "notification": "Ошибка",
                    "text": "Не удалось включить маяк.",
                    "format": "markdown",
                    "attachments": visit_card.worker_registered_main_menu_keyboard(),
                }
            log_admin_action_max(int(max_uid), "worker_beacon_on", "worker", int(worker_tg_id), "via_max")
            return registered_menu_static_reply(max_uid, "worker_reg_beacon")
        if payload == "worker_beacon_off":
            ok = disable_worker_beacon_max(worker_tg_id)
            if not ok:
                return {
                    "notification": "Ошибка",
                    "text": "Не удалось выключить маяк.",
                    "format": "markdown",
                    "attachments": visit_card.worker_registered_main_menu_keyboard(),
                }
            log_admin_action_max(int(max_uid), "worker_beacon_off", "worker", int(worker_tg_id), "via_max")
            return registered_menu_static_reply(max_uid, "worker_reg_beacon")
        if payload == "worker_reg_shifts":
            rows = list_worker_shifts_max(worker_tg_id, limit=20)
            return {
                "notification": " ",
                "text": _worker_shift_list_text(rows),
                "format": "markdown",
                "attachments": _worker_shift_list_keyboard(rows),
            }
        if re.match(r"^worker_shift_(\d+)$", payload or ""):
            m = re.match(r"^worker_shift_(\d+)$", payload or "")
            sid = int(m.group(1))
            auto_close_expired_breaks_max()
            card = get_worker_shift_assignment_max(sid, worker_tg_id)
            if not card:
                return {
                    "notification": "Не найдено",
                    "text": "Смена не найдена или не назначена вам.",
                    "format": "markdown",
                    "attachments": visit_card.worker_registered_main_menu_keyboard(),
                }
            active_break = get_active_break_max(sid, worker_tg_id)
            bstats = get_worker_break_stats_max(sid, worker_tg_id)
            return {
                "notification": " ",
                "text": _worker_shift_detail_text(card, active_break, bstats),
                "format": "markdown",
                "attachments": _worker_shift_detail_keyboard(card, active_break),
            }
        if payload.startswith("worker_shift_confirm_"):
            m = re.match(r"^worker_shift_confirm_(\d+)$", payload or "")
            if not m:
                return None
            sid = int(m.group(1))
            ok = confirm_worker_shift_max(sid, worker_tg_id)
            if not ok:
                return {
                    "notification": "Ошибка",
                    "text": "Не удалось подтвердить смену.",
                    "format": "markdown",
                    "attachments": visit_card.worker_registered_main_menu_keyboard(),
                }
            log_admin_action_max(int(max_uid), "worker_shift_confirm", "shift", sid, f"worker={worker_tg_id}")
            return registered_menu_static_reply(max_uid, f"worker_shift_{sid}")
        if payload.startswith("worker_shift_checkin_"):
            m = re.match(r"^worker_shift_checkin_(\d+)$", payload or "")
            if not m:
                return None
            sid = int(m.group(1))
            card = get_worker_shift_assignment_max(sid, worker_tg_id)
            if not card:
                return {
                    "notification": "Не найдено",
                    "text": "Смена не найдена или не назначена вам.",
                    "format": "markdown",
                    "attachments": visit_card.worker_registered_main_menu_keyboard(),
                }
            SESSIONS[int(max_uid)] = {
                "flow": "worker_shift",
                "step": "checkin_geo",
                "data": {"shift_id": sid},
            }
            return {
                "notification": "Чекин",
                "text": (
                    f"*Чекин · смена #{sid}*\n\n"
                    "Шаг 1/2: отправьте геолокацию (или координаты текстом: `55.751244, 37.618423`)."
                ),
                "format": "markdown",
                "attachments": inline_keyboard([[cb_btn("❌ Отмена", "main_menu")], [cb_btn("🔙 К смене", f"worker_shift_{sid}")]]),
            }
        if payload.startswith("worker_shift_checkout_"):
            m = re.match(r"^worker_shift_checkout_(\d+)$", payload or "")
            if not m:
                return None
            sid = int(m.group(1))
            card = get_worker_shift_assignment_max(sid, worker_tg_id)
            if not card:
                return {
                    "notification": "Не найдено",
                    "text": "Смена не найдена или не назначена вам.",
                    "format": "markdown",
                    "attachments": visit_card.worker_registered_main_menu_keyboard(),
                }
            SESSIONS[int(max_uid)] = {
                "flow": "worker_shift",
                "step": "checkout_geo",
                "data": {"shift_id": sid},
            }
            return {
                "notification": "Чекаут",
                "text": (
                    f"*Чекаут · смена #{sid}*\n\n"
                    "Шаг 1/2: отправьте геолокацию (или координаты текстом: `55.751244, 37.618423`)."
                ),
                "format": "markdown",
                "attachments": inline_keyboard([[cb_btn("❌ Отмена", "main_menu")], [cb_btn("🔙 К смене", f"worker_shift_{sid}")]]),
            }
        if payload.startswith("worker_break_menu_"):
            m = re.match(r"^worker_break_menu_(\d+)$", payload or "")
            if not m:
                return None
            sid = int(m.group(1))
            active_break = get_active_break_max(sid, worker_tg_id)
            kb_rows = [
                [cb_btn("🍽 Обед", f"worker_break_start_{sid}_lunch")],
                [cb_btn("🚬 Перекур", f"worker_break_start_{sid}_smoke")],
                [cb_btn("🛠 Тех. перерыв", f"worker_break_start_{sid}_tech")],
                [cb_btn("⏹ Завершить текущий", f"worker_break_stop_{sid}")],
                [cb_btn("🔙 К смене", f"worker_shift_{sid}")],
            ]
            text = "*Перерывы*\n\nВыберите действие."
            if active_break:
                bt = str(active_break.get("break_type") or "")
                text += (
                    f"\n\nСейчас активен: {BREAK_TYPE_LABELS_RU.get(bt, bt)}"
                    f"\nСтарт: {active_break.get('started_at') or '—'}"
                )
            return {"notification": " ", "text": text, "format": "markdown", "attachments": inline_keyboard(kb_rows)}
        if payload.startswith("worker_break_start_"):
            m = re.match(r"^worker_break_start_(\d+)_(lunch|smoke|tech)$", payload or "")
            if not m:
                return None
            sid = int(m.group(1))
            bt = m.group(2)
            card = get_worker_shift_assignment_max(sid, worker_tg_id) or {}
            if not card or str(card.get("assignment_status") or "") != "checked_in":
                return {
                    "notification": "Недоступно",
                    "text": "Перерыв доступен только после чек-ина на смене.",
                    "format": "markdown",
                    "attachments": inline_keyboard([[cb_btn("🔙 К смене", f"worker_shift_{sid}")]]),
                }
            stats = get_worker_break_stats_max(sid, worker_tg_id)
            err = _break_start_validation_message_max(card, stats, bt)
            if err:
                return {
                    "notification": "Недоступно",
                    "text": err,
                    "format": "markdown",
                    "attachments": inline_keyboard([[cb_btn("🔙 К смене", f"worker_shift_{sid}")]]),
                }
            ok = start_worker_break_max(sid, worker_tg_id, bt)
            if not ok:
                return {
                    "notification": "Ошибка",
                    "text": "Не удалось начать перерыв (возможно, уже есть активный).",
                    "format": "markdown",
                    "attachments": inline_keyboard([[cb_btn("🔙 К смене", f"worker_shift_{sid}")]]),
                }
            log_admin_action_max(
                int(max_uid),
                "worker_break_start",
                "shift",
                sid,
                f"worker={worker_tg_id};type={bt}",
            )
            return registered_menu_static_reply(max_uid, f"worker_shift_{sid}")
        if payload.startswith("worker_break_stop_"):
            m = re.match(r"^worker_break_stop_(\d+)$", payload or "")
            if not m:
                return None
            sid = int(m.group(1))
            ok = stop_worker_break_max(sid, worker_tg_id)
            if not ok:
                return {
                    "notification": "Ошибка",
                    "text": "Активный перерыв не найден.",
                    "format": "markdown",
                    "attachments": inline_keyboard([[cb_btn("🔙 К смене", f"worker_shift_{sid}")]]),
                }
            log_admin_action_max(int(max_uid), "worker_break_stop", "shift", sid, f"worker={worker_tg_id}")
            return registered_menu_static_reply(max_uid, f"worker_shift_{sid}")

    return None


async def process_callback(
    max_uid: int, payload: str, sender: dict[str, Any] | None
) -> dict[str, Any] | None:
    payload = _norm_cb_payload(payload)
    who = _sender_label(sender)

    if payload.startswith("visit_entry_returning:"):
        role = payload.rsplit(":", 1)[-1].strip().lower()
        if role not in ("client", "worker"):
            return None
        if role == "client" and has_max_active_executor_profile(max_uid):
            from user_identity import ROLE_SWITCH_VIA_ADMIN_FOOTER_RU

            return {
                "notification": "Недоступно",
                "text": (
                    "Исполнителям недоступен вход как заказчику. Откройте главное меню."
                    + ROLE_SWITCH_VIA_ADMIN_FOOTER_RU
                ),
                "format": "markdown",
                "attachments": visit_card.main_menu_keyboard(),
            }
        if role == "worker":
            blocked = _join_entry_blocked(max_uid)
            if blocked:
                return blocked
        return _start_role_entry_phone(max_uid, role)

    if payload.startswith("visit_entry_new:"):
        role = payload.rsplit(":", 1)[-1].strip().lower()
        if role == "client":
            return _begin_client_visit_registration_new(max_uid)
        if role == "worker":
            blocked = _join_entry_blocked(max_uid)
            if blocked:
                return blocked
            return _show_join_team_intro(max_uid)

    s = SESSIONS.get(max_uid)
    _reg_payloads = frozenset(
        {
            "admin_agency_hub",
            "admin_hub_ops",
            "admin_hub_hrm",
            "admin_hub_crm",
            "admin_hub_system",
            "admin_orders_funnel",
            "admin_orders_funnel_kp",
            "admin_orders_funnel_urgent",
            "admin_ops_shifts_active",
            "admin_ops_projects",
            "admin_ops_reports",
            "admin_hrm_join_recent",
            "admin_hrm_workers",
            "admin_hrm_worker_find",
            "admin_hrm_payments",
            "admin_hrm_payments_export",
            "admin_sys_admin_logs",
            "admin_sys_monitor",
            "admin_phone_login_btn",
            "admin_identity_dupes",
            "client_reg_projects",
            "client_reg_orders",
            "client_reg_settings",
            "client_reg_web",
            "open_web_cabinet",
            "client_cabinet",
            "worker_reg_profile",
            "worker_reg_shifts",
            "worker_reg_payments",
            "worker_reg_beacon",
            "worker_beacon_on",
            "worker_beacon_off",
        }
    )
    if payload in _reg_payloads or payload.startswith(
        (
            "admin_funnel__",
            "admin_order_detail_",
            "admin_order_stage_",
            "admin_ops_shift_detail_",
            "admin_ops_project_detail_",
            "admin_hrm_payment_",
            "admin_hrm_paystatus_",
            "admin_hrm_worker_detail_",
            "worker_shift_",
            "worker_break_menu_",
            "worker_break_start_",
            "worker_break_stop_",
        )
    ):
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
        # Чистый контур регистрации заказчика: обнуляем хвосты возможного order/CP сценария.
        keep = {"canonical_user_tg_id": data.get("canonical_user_tg_id")}
        data.clear()
        if keep.get("canonical_user_tg_id"):
            data["canonical_user_tg_id"] = keep["canonical_user_tg_id"]
        s["step"] = "company_name"
        return {
            "notification": "Согласие принято ✅",
            "text": (
                "Давайте познакомимся.\n\n"
                "Укажите *название юрлица заказчика*.\n\n"
                "_Образец:_ `ООО «Ромашка»`"
            ),
            "format": "markdown",
            "attachments": visit_card.back_to_main_keyboard(),
        }

    if flow == "client_visit" and step == "confirm" and payload == "confirm_client_visit_yes":
        username = (sender or {}).get("username") if isinstance(sender, dict) else ""
        try:
            save_max_visit_client_verified(
                max_uid,
                str(username or ""),
                _client_visit_payload_for_save(data),
            )
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
        s["step"] = "confirm"
        return {
            "text": "Что хотите исправить?",
            "format": "markdown",
            "attachments": visit_card.client_reg_edit_menu_keyboard(),
        }

    if flow == "client_visit" and step == "confirm" and payload in {"vredit:c", "vredit:i", "vredit:n", "vredit:p", "vredit:e"}:
        edit_code = payload.split(":", 1)[-1].strip().lower()
        data["visit_reg_edit_code"] = edit_code
        if edit_code == "c":
            s["step"] = "company_name"
            return {
                "text": "Укажите *название юрлица заказчика*.\n\n_Образец:_ `ООО «Ромашка»`",
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if edit_code == "i":
            s["step"] = "inn"
            return {
                "text": "Укажите *ИНН юрлица* (10 или 12 цифр).\n\n_Образец:_ `7707083893`",
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if edit_code == "n":
            s["step"] = "contact_name"
            return {
                "text": "Введите *ФИО контактного лица*.\n\n_Образец:_ `Иванов Иван Иванович`",
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if edit_code == "p":
            s["step"] = "phone"
            return {
                "text": (
                    "Отправьте *телефон контактного лица* кнопкой ниже или введите вручную.\n\n"
                    "_Образец:_ `+79001234567`"
                ),
                "format": "markdown",
                "attachments": phone_input_keyboard(),
            }
        s["step"] = "email"
        return {
            "text": "Введите *email* контактного лица.\n\n_Образец:_ `client@company.ru`",
            "format": "markdown",
            "attachments": visit_card.back_to_main_keyboard(),
        }

    if flow == "client_visit" and step == "confirm" and payload == "visitreg_back":
        data.pop("visit_reg_edit_code", None)
        return {
            "text": _client_visit_preview_text(data),
            "format": "markdown",
            "attachments": visit_card.client_reg_confirm_keyboard(),
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
            pos = str(data.get("position") or "").strip()
            data["join_profession_titles"] = [pos]
            data["position"] = pos
            s["step"] = "profession_summary"
            return {
                "notification": "Согласие принято ✅",
                "text": _profession_summary_markdown([pos]),
                "format": "markdown",
                "attachments": visit_card.profession_summary_keyboard(edit_mode=False),
            }
        data["join_profession_titles"] = []
        data["position"] = ""
        s["step"] = "profession_category"
        return {
            "notification": "Согласие принято ✅",
            "text": "*ВЫБОР ПРОФЕССИИ*\n\nВыберите категорию 👇",
            "format": "markdown",
            "attachments": visit_card.profession_categories_keyboard(),
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

    if flow == "join" and step == "profession_summary":
        if payload == "prof_add_another":
            s["step"] = "profession_category"
            return {
                "notification": " ",
                "text": "*ВЫБОР ПРОФЕССИИ*\n\nВыберите категорию 👇",
                "format": "markdown",
                "attachments": visit_card.profession_categories_keyboard(),
            }
        if payload == "prof_done":
            titles = list(data.get("join_profession_titles") or [])
            if not titles and (data.get("position") or "").strip():
                titles = [str(data.get("position") or "").strip()]
            if not titles:
                return {
                    "notification": "Добавьте хотя бы одну профессию",
                    "text": _profession_summary_markdown([]),
                    "format": "markdown",
                    "attachments": visit_card.profession_summary_keyboard(),
                }
            if data.get("join_edit_mode"):
                return _join_go_to_review(s, data)
            s["step"] = "full_name"
            return {
                "notification": " ",
                "text": _basic_info_intro(),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if payload == "prof_edit_reset":
            data["join_profession_titles"] = []
            data["position"] = ""
            s["step"] = "profession_category"
            return {
                "notification": "Список очищен",
                "text": "*ВЫБОР ПРОФЕССИИ*\n\nВыберите категорию 👇",
                "format": "markdown",
                "attachments": visit_card.profession_categories_keyboard(),
            }

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
            raw, added = _append_join_profession_title(data, title)
            if not added:
                return {
                    "notification": "Уже в списке",
                    "text": _profession_summary_markdown(raw),
                    "format": "markdown",
                    "attachments": visit_card.profession_summary_keyboard(
                        edit_mode=bool(data.get("join_edit_mode"))
                    ),
                }
            return _join_goto_profession_summary(s, data, notification=f"Профессия: {title}")
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

    if flow == "admin_hrm_find_worker" and step == "query":
        q = (text or "").strip()
        if not q:
            return {
                "text": "Введите ФИО, телефон или user_id.",
                "format": "markdown",
                "attachments": visit_card.admin_hub_hrm_keyboard(),
            }
        rows = search_workers_admin_max(q, limit=20)
        clear_session(max_uid)
        if not rows:
            return {
                "notification": "Не найдено",
                "text": (
                    "*Найти исполнителя*\n\n"
                    "Совпадений нет. Проверьте запрос и попробуйте снова."
                ),
                "format": "markdown",
                "attachments": inline_keyboard(
                    [
                        [cb_btn("🔁 Новый поиск", "admin_hrm_worker_find")],
                        [cb_btn("🔙 HRM", "admin_hub_hrm")],
                    ]
                ),
            }
        lines = ["*Результаты поиска исполнителей*", ""]
        kb_rows: list[list[dict]] = []
        for row in rows:
            wid = int(row.get("user_id") or 0)
            fio = (row.get("full_name") or "—").strip()
            prof = (row.get("profession") or "—").strip()
            st = (row.get("status") or "new").strip()
            lines.append(f"• {fio} ({wid}) · {prof} · `{st}`")
            kb_rows.append([cb_btn(f"👷 {fio[:40]}", f"admin_hrm_worker_detail_{wid}")])
        kb_rows.append([cb_btn("🔁 Новый поиск", "admin_hrm_worker_find")])
        kb_rows.append([cb_btn("🔙 HRM", "admin_hub_hrm")])
        return {
            "notification": " ",
            "text": "\n".join(lines)[:3900],
            "format": "markdown",
            "attachments": inline_keyboard(kb_rows),
        }

    if flow == "role_entry" and step == "phone":
        role = str(data.get("intended_role") or "client")
        v = _extract_phone_from_incoming(text, message_body)
        if not v:
            return {
                "text": (
                    "💡 Не удалось распознать номер. Нажмите *Поделиться контактом* "
                    "или введите мобильный РФ, например +79161234567."
                ),
                "format": "markdown",
                "attachments": phone_input_keyboard(),
            }
        from user_identity import resolve_registration_by_phone

        res = resolve_registration_by_phone(int(max_uid), v, role)  # type: ignore[arg-type]
        from visit_phone_login_log import log_visit_phone_login

        un = (sender or {}).get("username") if isinstance(sender, dict) else ""
        log_visit_phone_login(
            source="max",
            platform_user_id=int(max_uid),
            phone=v,
            intended_role=role,
            outcome="not_found" if res.action == "continue" else res.action,
            username=str(un or ""),
        )
        if res.action == "continue":
            clear_session(max_uid)
            return {
                "notification": "Не найдено",
                "text": (
                    "По этому номеру регистрация *не найдена*.\n\n"
                    "Если вы ещё не регистрировались — нажмите кнопку ниже. "
                    "Или укажите другой номер."
                ),
                "format": "markdown",
                "attachments": visit_card.role_not_found_keyboard(role),
            }
        blocked = _phone_resolve_or_none(max_uid, s, v, role)
        if blocked:
            return blocked
        return None

    if flow == "worker_shift":
        sid = int((data.get("shift_id") or 0))
        if sid <= 0:
            clear_session(max_uid)
            return {
                "notification": "Ошибка",
                "text": "Не удалось определить смену. Откройте раздел «Мои смены» снова.",
                "format": "markdown",
                "attachments": visit_card.worker_registered_main_menu_keyboard(),
            }
        worker_tg_id = resolve_tg_id_for_max_user(int(max_uid))
        if step in ("checkin_geo", "checkout_geo"):
            loc = _location_from_body(message_body, text)
            if not loc:
                return {
                    "notification": "Нужна геолокация",
                    "text": (
                        f"*Смена #{sid}*\n\n"
                        "Не вижу координаты. Отправьте геолокацию или введите координаты текстом "
                        "в формате `55.751244, 37.618423`."
                    ),
                    "format": "markdown",
                    "attachments": inline_keyboard([[cb_btn("🔙 К смене", f"worker_shift_{sid}")], [cb_btn("🏠 Меню", "main_menu")]]),
                }
            data["geo_lat"] = float(loc[0])
            data["geo_lng"] = float(loc[1])
            if step == "checkin_geo":
                s["step"] = "checkin_photo"
                return {
                    "notification": "Шаг 2",
                    "text": (
                        f"*Чекин · смена #{sid}*\n\n"
                        "Шаг 2/2: отправьте фото (селфи на точке)."
                    ),
                    "format": "markdown",
                    "attachments": inline_keyboard([[cb_btn("🔙 К смене", f"worker_shift_{sid}")], [cb_btn("🏠 Меню", "main_menu")]]),
                }
            s["step"] = "checkout_photo"
            return {
                "notification": "Шаг 2",
                "text": (
                    f"*Чекаут · смена #{sid}*\n\n"
                    "Шаг 2/2: отправьте фото с завершения смены."
                ),
                "format": "markdown",
                "attachments": inline_keyboard([[cb_btn("🔙 К смене", f"worker_shift_{sid}")], [cb_btn("🏠 Меню", "main_menu")]]),
            }
        if step in ("checkin_photo", "checkout_photo"):
            photo_ref = _image_ref_from_body(message_body)
            if not photo_ref:
                return {
                    "notification": "Нужно фото",
                    "text": "Пришлите фото вложением, чтобы завершить операцию.",
                    "format": "markdown",
                    "attachments": inline_keyboard([[cb_btn("🔙 К смене", f"worker_shift_{sid}")], [cb_btn("🏠 Меню", "main_menu")]]),
                }
            lat = float(data.get("geo_lat") or 0.0)
            lng = float(data.get("geo_lng") or 0.0)
            loc_s = f"{lat:.6f},{lng:.6f}" if lat and lng else None
            if step == "checkin_photo":
                ok = checkin_worker_shift_max(sid, worker_tg_id, photo_url=photo_ref, checkin_location=loc_s)
                if not ok:
                    return {
                        "notification": "Ошибка",
                        "text": "Не удалось выполнить чекин. Проверьте статус смены и попробуйте снова.",
                        "format": "markdown",
                        "attachments": inline_keyboard([[cb_btn("🔙 К смене", f"worker_shift_{sid}")], [cb_btn("🏠 Меню", "main_menu")]]),
                    }
                log_admin_action_max(int(max_uid), "worker_checkin", "shift", sid, f"worker={worker_tg_id};loc={loc_s or '-'}")
                clear_session(max_uid)
                return registered_menu_static_reply(max_uid, f"worker_shift_{sid}")
            ok = checkout_worker_shift_max(sid, worker_tg_id, photo_url=photo_ref, checkout_location=loc_s)
            if not ok:
                return {
                    "notification": "Ошибка",
                    "text": "Не удалось выполнить чекаут. Проверьте статус смены и попробуйте снова.",
                    "format": "markdown",
                    "attachments": inline_keyboard([[cb_btn("🔙 К смене", f"worker_shift_{sid}")], [cb_btn("🏠 Меню", "main_menu")]]),
                }
            log_admin_action_max(int(max_uid), "worker_checkout", "shift", sid, f"worker={worker_tg_id};loc={loc_s or '-'}")
            clear_session(max_uid)
            return registered_menu_static_reply(max_uid, f"worker_shift_{sid}")

    if step == "consent":
        if flow == "client_visit":
            return {
                "text": _consent_gate_text("меню заказчика"),
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
            if (data.get("visit_reg_edit_code") or "").strip().lower() == "c":
                data.pop("visit_reg_edit_code", None)
                s["step"] = "confirm"
                return {
                    "text": _client_visit_preview_text(data),
                    "format": "markdown",
                    "attachments": visit_card.client_reg_confirm_keyboard(),
                }
            s["step"] = "inn"
            return {
                "text": "Укажите *ИНН юрлица* (10 или 12 цифр).\n\n_Образец:_ `7707083893`",
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
            if (data.get("visit_reg_edit_code") or "").strip().lower() == "i":
                data.pop("visit_reg_edit_code", None)
                s["step"] = "confirm"
                return {
                    "text": _client_visit_preview_text(data),
                    "format": "markdown",
                    "attachments": visit_card.client_reg_confirm_keyboard(),
                }
            s["step"] = "contact_name"
            return {
                "text": "Введите *ФИО контактного лица*.\n\n_Образец:_ `Иванов Иван Иванович`",
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
            if (data.get("visit_reg_edit_code") or "").strip().lower() == "n":
                data.pop("visit_reg_edit_code", None)
                s["step"] = "confirm"
                return {
                    "text": _client_visit_preview_text(data),
                    "format": "markdown",
                    "attachments": visit_card.client_reg_confirm_keyboard(),
                }
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
                "text": (
                    "Отправьте *телефон контактного лица* кнопкой ниже или введите вручную.\n\n"
                    "_Образец:_ `+79001234567`"
                ),
                "format": "markdown",
                "attachments": phone_input_keyboard(),
            }
        if step == "email":
            if not validate_email(text.strip()):
                return {
                    "text": "❌ Введите корректный email. Пример: client@company.ru",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["contact_email"] = text.strip()
            data.pop("visit_reg_edit_code", None)
            s["step"] = "confirm"
            return {
                "text": _client_visit_preview_text(data),
                "format": "markdown",
                "attachments": visit_card.client_reg_confirm_keyboard(),
            }
        if step == "phone":
            v = _extract_phone_from_incoming(text, message_body) or validate_phone(text)
            if not v:
                return {
                    "text": (
                        "❌ Не удалось распознать номер. Нажмите *Поделиться контактом* "
                        "или введите +7XXXXXXXXXX."
                    ),
                    "format": "markdown",
                    "attachments": phone_input_keyboard(),
                }
            data["phone"] = v
            blocked = _phone_resolve_or_none(max_uid, s, v, "client")
            if blocked:
                return blocked
            if (data.get("visit_reg_edit_code") or "").strip().lower() == "p":
                data.pop("visit_reg_edit_code", None)
                s["step"] = "confirm"
                return {
                    "text": _client_visit_preview_text(data),
                    "format": "markdown",
                    "attachments": visit_card.client_reg_confirm_keyboard(),
                }
            s["step"] = "email"
            return {
                "text": (
                    "Номер сохранён.\n\n"
                    "Введите *email* контактного лица.\n\n"
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
            raw, added = _append_join_profession_title(data, t)
            if not added:
                return {
                    "notification": "Уже в списке",
                    "text": _profession_summary_markdown(raw),
                    "format": "markdown",
                    "attachments": visit_card.profession_summary_keyboard(
                        edit_mode=bool(data.get("join_edit_mode"))
                    ),
                }
            return _join_goto_profession_summary(s, data, notification="✅ Профессию записали")
        if step == "profession_summary":
            return {
                "text": (
                    "Нажмите кнопку под сообщением: добавить профессию, "
                    "перейти к ФИО или вернитесь в меню."
                ),
                "format": "markdown",
                "attachments": visit_card.profession_summary_keyboard(
                    edit_mode=bool(data.get("join_edit_mode"))
                ),
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
                    "text": f"💡 {visit_join_validators.join_validation_error_text('full_name_invalid')}",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["full_name"] = text.strip()
            s["step"] = "phone"
            return {
                "text": (
                    "📞 *Укажите номер телефона*\n\n"
                    "Нажмите *Поделиться контактом* или введите вручную.\n\n"
                    "_Пример: +7 916 123-45-67_"
                ),
                "format": "markdown",
                "attachments": phone_input_keyboard(),
            }
        if step == "phone":
            v = _extract_phone_from_incoming(text, message_body)
            if not v:
                return {
                    "text": f"💡 {visit_join_validators.join_validation_error_text('phone_mobile_ru_invalid')}",
                    "format": "markdown",
                    "attachments": phone_input_keyboard(),
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
                    "text": visit_join_validators.join_validation_error_text("inn_invalid"),
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
            if len(d) != 12 or not visit_join_validators.validate_inn_digits(d):
                return {
                    "text": f"💡 {visit_join_validators.join_validation_error_text('inn_invalid')}",
                    "format": "markdown",
                    "attachments": visit_card.back_to_main_keyboard(),
                }
            data["tax_inn"] = d
            return _join_begin_identity_chain(s)

        if step == "snils":
            if not visit_join_validators.validate_join_snils(text):
                return {
                    "text": f"💡 {visit_join_validators.join_validation_error_text('snils_invalid')}",
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
                    "text": f"💡 {visit_join_validators.join_validation_error_text('email_invalid')}",
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
                    "text": visit_join_validators.join_validation_error_text("portfolio_url_invalid"),
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
                    "text": visit_join_validators.join_validation_error_text("inn_invalid"),
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
                    "text": visit_join_validators.join_validation_error_text("medbook_expiry_invalid"),
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
                    "text": f"💡 {visit_join_validators.join_validation_error_text('passport_sn_invalid')}",
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
                    "text": f"💡 {visit_join_validators.join_validation_error_text('passport_issued_by_invalid')}",
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
                    "text": f"💡 {visit_join_validators.join_validation_error_text('passport_issue_date_invalid')}",
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
                    "text": f"💡 {visit_join_validators.join_validation_error_text('registration_address_invalid')}",
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
                    "text": f"💡 {visit_join_validators.join_validation_error_text('work_city_invalid')}",
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
                    "text": err_m or visit_join_validators.join_validation_error_text("metro_invalid"),
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
