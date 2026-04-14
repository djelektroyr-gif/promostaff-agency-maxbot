"""
Сценарии из PROMOSTAFF-AGENCY BOT (FSM): расчёт, вопрос, анкета в команду.
Состояние в памяти процесса (без SQLite). Уведомления — notify.notify_agency_admins.
"""
from __future__ import annotations

import logging
import random
import time
from typing import Any

from config import COMPANY_NAME, WEBSITE_URL

import visit_card
from funnel_store import funnel_touch_complete
from notify import notify_agency_admins

logger = logging.getLogger(__name__)

SESSIONS: dict[int, dict[str, Any]] = {}


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


def start_order(max_uid: int) -> dict[str, Any]:
    clear_session(max_uid)
    SESSIONS[max_uid] = {"flow": "order", "step": "event_type", "data": {}}
    return {
        "text": (
            "💰 *Заказ расчёта стоимости*\n\n"
            "Пожалуйста, ответьте на несколько вопросов.\n\n"
            "📋 *Шаг 1/6*\n"
            "Укажите тип мероприятия (выставка, концерт, корпоратив и т.д.):"
        ),
        "format": "markdown",
        "attachments": visit_card.back_to_main_keyboard(),
    }


def start_question(max_uid: int) -> dict[str, Any]:
    clear_session(max_uid)
    SESSIONS[max_uid] = {"flow": "question", "step": "text", "data": {}}
    return {
        "text": (
            "❓ *Задать вопрос*\n\n"
            "Напишите ваш вопрос, и мы ответим в ближайшее время:"
        ),
        "format": "markdown",
        "attachments": visit_card.back_to_main_keyboard(),
    }


def start_join(max_uid: int) -> dict[str, Any]:
    clear_session(max_uid)
    SESSIONS[max_uid] = {"flow": "join", "step": "full_name", "data": {}}
    return {
        "text": (
            "📝 *Анкета кандидата*\n\n"
            "Пожалуйста, ответьте на несколько вопросов.\n\n"
            "*Шаг 1/5*\n"
            "Укажите ваше полное ФИО:"
        ),
        "format": "markdown",
        "attachments": visit_card.back_to_main_keyboard(),
    }


POSITIONS = {
    "pos_helper": "Хелпер",
    "pos_cloakroom": "Гардеробщик",
    "pos_parking": "Парковщик",
    "pos_promo": "Промоутер / Хостес",
    "pos_supervisor": "Супервайзер",
    "pos_other": "Другое",
}


def join_select_position(max_uid: int, payload: str) -> dict[str, Any] | None:
    s = SESSIONS.get(max_uid)
    if not s or s.get("flow") != "join" or s.get("step") != "position_pick":
        return None
    pos = POSITIONS.get(payload, "Не указана")
    s["data"]["position"] = pos
    s["step"] = "city"
    return {
        "text": (
            "📍 *Шаг 4/5*\n"
            "Укажите ваш город проживания:"
        ),
        "format": "markdown",
        "attachments": visit_card.back_to_main_keyboard(),
    }


def _format_order_plain(data: dict[str, Any], order_id: int, who: str) -> str:
    return (
        f"Новая заявка на расчёт #{order_id}\n"
        f"================================\n\n"
        f"От: {who}\n\n"
        f"📋 Тип мероприятия: {data.get('event_type', '—')}\n"
        f"📍 Город: {data.get('city', '—')}\n"
        f"📅 Дата: {data.get('event_date', '—')}\n"
        f"👥 Персонал: {data.get('staff_count', '—')}\n"
        f"📞 Телефон: {data.get('contact_phone', '—')}\n"
        f"👤 Имя: {data.get('contact_name', '—')}\n\n"
        f"---\n{COMPANY_NAME}\nСайт: {WEBSITE_URL}\n"
    )


def _format_question_plain(q: str, qid: int, who: str) -> str:
    return (
        f"Новый вопрос #{qid}\n"
        f"================================\n\n"
        f"От: {who}\n\n"
        f"❓ Вопрос:\n{q}\n\n"
        f"---\n{COMPANY_NAME}\nСайт: {WEBSITE_URL}\n"
    )


def _format_join_plain(data: dict[str, Any], rid: int, who: str) -> str:
    return (
        f"Новая заявка в команду #{rid}\n"
        f"================================\n\n"
        f"От: {who}\n\n"
        f"👤 ФИО: {data.get('full_name', '—')}\n"
        f"📞 Телефон: {data.get('phone', '—')}\n"
        f"💼 Должность: {data.get('position', '—')}\n"
        f"📍 Город: {data.get('city', '—')}\n"
        f"📝 Опыт: {data.get('experience', '—')}\n\n"
        f"---\n{COMPANY_NAME}\nСайт: {WEBSITE_URL}\n"
    )


async def _notify_plain(subject: str, plain: str) -> None:
    try:
        await notify_agency_admins(subject, plain)
    except Exception:
        logger.exception("notify_agency_admins failed")


async def process_text(max_uid: int, text: str, sender: dict[str, Any] | None) -> dict[str, Any] | None:
    """Ответ пользователю при вводе текста в рамках FSM; None — не наше сообщение."""
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
            "text": (
                "✅ *Вопрос отправлен!*\n\n"
                "Спасибо за обращение! Мы ответим вам в ближайшее время."
            ),
            "format": "markdown",
            "attachments": visit_card.main_menu_keyboard(),
        }

    if flow == "order":
        if step == "event_type":
            data["event_type"] = text
            s["step"] = "city"
            return {
                "text": "📍 *Шаг 2/6*\nУкажите город проведения мероприятия:",
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "city":
            data["city"] = text
            s["step"] = "event_date"
            return {
                "text": "📅 *Шаг 3/6*\nУкажите дату мероприятия (или период):",
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "event_date":
            data["event_date"] = text
            s["step"] = "staff_count"
            return {
                "text": (
                    "👥 *Шаг 4/6*\n"
                    "Какое количество и каких специалистов требуется?\n"
                    "(например: 5 хелперов, 2 гардеробщика)"
                ),
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "staff_count":
            data["staff_count"] = text
            s["step"] = "contact_phone"
            return {
                "text": "📞 *Шаг 5/6*\nУкажите контактный телефон для связи:",
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "contact_phone":
            data["contact_phone"] = text
            s["step"] = "contact_name"
            return {
                "text": "👤 *Шаг 6/6*\nКак к вам обращаться? (Имя)",
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "contact_name":
            data["contact_name"] = text
            oid = _new_id()
            plain = _format_order_plain(data, oid, who)
            await _notify_plain(f"Новая заявка на расчёт #{oid}", plain)
            funnel_touch_complete(max_uid)
            clear_session(max_uid)
            return {
                "text": (
                    "✅ *Заявка принята!*\n\n"
                    "Спасибо за обращение! Мы подготовим индивидуальное "
                    "коммерческое предложение в течение 24 часов.\n\n"
                    f"Номер вашей заявки: *{oid}*"
                ),
                "format": "markdown",
                "attachments": visit_card.main_menu_keyboard(),
            }

    if flow == "join":
        if step == "full_name":
            data["full_name"] = text
            s["step"] = "phone"
            return {
                "text": "📞 *Шаг 2/5*\nУкажите контактный телефон:",
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "phone":
            data["phone"] = text
            s["step"] = "position_pick"
            return {
                "text": "💼 *Шаг 3/5*\nВыберите желаемую должность:",
                "format": "markdown",
                "attachments": visit_card.join_position_keyboard(),
            }
        if step == "city":
            data["city"] = text
            s["step"] = "experience"
            return {
                "text": "📝 *Шаг 5/5*\nКратко опишите ваш опыт работы (можно без опыта):",
                "format": "markdown",
                "attachments": visit_card.back_to_main_keyboard(),
            }
        if step == "experience":
            data["experience"] = text
            rid = _new_id()
            plain = _format_join_plain(data, rid, who)
            await _notify_plain(f"Новая заявка в команду #{rid}", plain)
            funnel_touch_complete(max_uid)
            clear_session(max_uid)
            return {
                "text": (
                    "✅ *Заявка принята!*\n\n"
                    "Спасибо за интерес к работе в PROMOSTAFF AGENCY!\n"
                    "Мы рассмотрим вашу анкету и свяжемся с вами в ближайшее время.\n\n"
                    f"Номер вашей заявки: *{rid}*"
                ),
                "format": "markdown",
                "attachments": visit_card.main_menu_keyboard(),
            }

    return None
