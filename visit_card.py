"""
Тексты и клавиатуры визитки PROMOSTAFF Agency в MAX.
Колбэки: префикс v: (visit), короткие значения для payload.
"""
from __future__ import annotations

from typing import Any

from config import AGENCY_EMAIL, AGENCY_PHONE, AGENCY_SITE_URL, PRO_TELEGRAM_BOT_URL
from max_attachments import cb_btn, inline_keyboard, link_btn

P_MAIN = "v:main"
P_ABOUT = "v:about"
P_SERVICES = "v:services"
P_CLIENT = "v:client"
P_STAFF = "v:staff"
P_CONTACT = "v:contact"


def _row_back_main() -> list[dict]:
    return [cb_btn("◀ Главное меню", P_MAIN)]


def _optional_links_row() -> list[dict] | None:
    row: list[dict] = []
    if AGENCY_SITE_URL.startswith("http"):
        row.append(link_btn("Сайт", AGENCY_SITE_URL))
    if PRO_TELEGRAM_BOT_URL.startswith("http"):
        row.append(link_btn("Бот PROMOSTAFF PRO", PRO_TELEGRAM_BOT_URL))
    return row if row else None


def attachments_main_menu() -> list[dict]:
    rows: list[list[dict]] = [
        [cb_btn("О компании", P_ABOUT), cb_btn("Услуги", P_SERVICES)],
        [cb_btn("Заказчикам", P_CLIENT), cb_btn("Исполнителям", P_STAFF)],
        [cb_btn("Контакты", P_CONTACT)],
    ]
    extra = _optional_links_row()
    if extra:
        rows.append(extra)
    return inline_keyboard(rows)


def attachments_submenu() -> list[dict]:
    return inline_keyboard([_row_back_main()])


def attachments_contacts_menu() -> list[dict]:
    rows: list[list[dict]] = []
    if AGENCY_PHONE:
        digits = AGENCY_PHONE.strip().replace(" ", "")
        if digits:
            rows.append([link_btn("Позвонить", f"tel:{digits}")])
    if AGENCY_EMAIL and "@" in AGENCY_EMAIL:
        rows.append([link_btn("Написать на email", f"mailto:{AGENCY_EMAIL}")])
    rows.append(_row_back_main())
    return inline_keyboard(rows)


def text_welcome() -> str:
    return (
        "🏢 *PROMOSTAFF Agency*\n\n"
        "Подбор персонала под промо, корпоративы, выставки и события.\n\n"
        "Выберите раздел ниже или отправьте команду `/start`."
    )


def text_about() -> str:
    return (
        "*О компании*\n\n"
        "PROMOSTAFF Agency — кадровое агентство для проектного персонала: "
        "промо-модели, хостес, мерчендайзинг, администраторы, помощники на мероприятиях.\n\n"
        "Работаем прозрачно: договор, смены, отчётность. Основной продукт для регистрации и смен — "
        "экосистема *PROMOSTAFF PRO* (Telegram; при необходимости — MAX)."
    )


def text_services() -> str:
    return (
        "*Услуги*\n\n"
        "• Подбор исполнителей под задачу и бюджет\n"
        "• Сопровождение проекта: бриф, ставки, выходы на смены\n"
        "• Проверка квалификации и документов (в рамках PRO)\n"
        "• Консультация заказчика по формату и численности персонала\n\n"
        "Детали — по запросу через контакты или основной бот PRO."
    )


def text_for_clients() -> str:
    return (
        "*Заказчикам*\n\n"
        "Опишите даты, город, формат мероприятия, роли и численность — подготовим предложение по ставкам и составу.\n\n"
        "Для учётных записей исполнителей и заявок на смены используйте *PROMOSTAFF PRO*."
    )


def text_for_staff() -> str:
    return (
        "*Исполнителям*\n\n"
        "Регистрируйтесь в *PROMOSTAFF PRO*, заполните профиль и документы — так вы попадёте в подбор на смены.\n\n"
        "Этот чат в MAX — визитка агентства; сценарии регистрации и смен ведутся в PRO."
    )


def text_contacts() -> str:
    lines = ["*Контакты*\n"]
    if AGENCY_PHONE:
        lines.append(f"Телефон: `{AGENCY_PHONE}`")
    else:
        lines.append("Телефон: уточняется (задайте `AGENCY_PHONE` в переменных окружения).")
    if AGENCY_EMAIL:
        lines.append(f"Email: `{AGENCY_EMAIL}`")
    else:
        lines.append("Email: уточняется (`AGENCY_EMAIL`).")
    if AGENCY_SITE_URL.startswith("http"):
        lines.append(f"Сайт: {AGENCY_SITE_URL}")
    lines.append("")
    lines.append("Ссылки на сайт и бот PRO также доступны кнопками в главном меню (если заданы в env).")
    return "\n".join(lines)


def message_for_payload(payload: str) -> dict[str, Any] | None:
    """Тело сообщения для ответа на callback (и для дублирования логики текста)."""
    p = (payload or "").strip()
    if p == P_MAIN:
        return {"text": text_welcome(), "format": "markdown", "attachments": attachments_main_menu()}
    if p == P_ABOUT:
        return {"text": text_about(), "format": "markdown", "attachments": attachments_submenu()}
    if p == P_SERVICES:
        return {"text": text_services(), "format": "markdown", "attachments": attachments_submenu()}
    if p == P_CLIENT:
        return {"text": text_for_clients(), "format": "markdown", "attachments": attachments_submenu()}
    if p == P_STAFF:
        return {"text": text_for_staff(), "format": "markdown", "attachments": attachments_submenu()}
    if p == P_CONTACT:
        return {"text": text_contacts(), "format": "markdown", "attachments": attachments_contacts_menu()}
    return None
