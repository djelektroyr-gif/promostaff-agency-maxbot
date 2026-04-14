"""
Визитка MAX — копия сценария PROMOSTAFF-AGENCY BOT (Telegram): keyboards.py + тексты из handlers.py.
Колбэки payload совпадают с callback_data в Telegram (about, main_menu, …).
"""
from __future__ import annotations

from typing import Any

from config import (
    COMPANY_NAME,
    CONTACT_EMAIL,
    CONTACT_PHONE,
    CONTACT_TELEGRAM,
    PORTFOLIO_URL,
    WEBSITE_URL,
    contact_phone_tel,
    contact_telegram_url,
)
from max_attachments import cb_btn, inline_keyboard, link_btn

# Пэйлоады, которые обрабатывает visit_flows (не статичное редактирование одного сообщения).
FLOW_PAYLOADS = frozenset(
    {
        "calculate",
        "ask_question",
        "fill_anketa",
        "main_menu",
        "back_to_main",
        "back",
        "none",
    }
)
POS_PREFIX = "pos_"


def main_menu_keyboard() -> list[dict]:
    rows: list[list[dict]] = [
        [cb_btn("📋 О PROMOSTAFF AGENCY", "about")],
        [cb_btn("⭐ Преимущества", "advantages")],
        [cb_btn("🔄 Как мы работаем", "how_we_work")],
        [link_btn("💬 Отзывы", PORTFOLIO_URL)],
        [cb_btn("💰 Заказать расчёт", "calculate")],
        [link_btn("🌐 Наш сайт", WEBSITE_URL)],
        [cb_btn("❓ Задать вопрос", "ask_question")],
        [cb_btn("👥 Хочу в команду", "join_team")],
        [cb_btn("📞 Связаться с менеджером", "contact_manager")],
    ]
    return inline_keyboard(rows)


def back_to_main_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("🏠 В главное меню", "main_menu")],
            [cb_btn("⬅️ Назад", "back")],
        ]
    )


def advantages_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("💰 Заказать расчёт", "calculate")],
            [link_btn("💬 Отзывы клиентов", PORTFOLIO_URL)],
            [cb_btn("⬅️ Назад", "back_to_main")],
            [cb_btn("🏠 В главное меню", "main_menu")],
        ]
    )


def about_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("⭐ Преимущества", "advantages")],
            [cb_btn("💰 Заказать расчёт", "calculate")],
            [link_btn("💬 Отзывы", PORTFOLIO_URL)],
            [cb_btn("⬅️ Назад", "back_to_main")],
            [cb_btn("🏠 В главное меню", "main_menu")],
        ]
    )


def how_we_work_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("💰 Заказать расчёт", "calculate")],
            [cb_btn("⬅️ Назад", "back_to_main")],
            [cb_btn("🏠 В главное меню", "main_menu")],
        ]
    )


def contact_keyboard() -> list[dict]:
    tel = contact_phone_tel()
    rows: list[list[dict]] = [
        [link_btn(f"📞 Позвонить: {CONTACT_PHONE}", f"tel:{tel}")],
        [link_btn("💬 Написать в Telegram", contact_telegram_url())],
        [link_btn(f"📧 {CONTACT_EMAIL}", f"mailto:{CONTACT_EMAIL}")],
        [cb_btn("🏠 В главное меню", "main_menu")],
    ]
    return inline_keyboard(rows)


def join_team_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("📝 Заполнить анкету", "fill_anketa")],
            [cb_btn("📋 Требования к кандидатам", "requirements")],
            [cb_btn("📂 Открытые вакансии", "vacancies")],
            [cb_btn("🏠 В главное меню", "main_menu")],
        ]
    )


def join_position_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("Хелпер", "pos_helper")],
            [cb_btn("Гардеробщик", "pos_cloakroom")],
            [cb_btn("Парковщик", "pos_parking")],
            [cb_btn("Промоутер / Хостес", "pos_promo")],
            [cb_btn("Супервайзер", "pos_supervisor")],
            [cb_btn("Другое", "pos_other")],
            [cb_btn("🏠 В главное меню", "main_menu")],
        ]
    )


def vacancies_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("📝 Хочу на эту вакансию", "fill_anketa")],
            [cb_btn("⬅️ Назад", "join_team")],
            [cb_btn("🏠 В главное меню", "main_menu")],
        ]
    )


def text_welcome() -> str:
    return (
        f"🏢 *{COMPANY_NAME}*\n\n"
        "Ваш надёжный партнёр в подборе временного персонала.\n"
        "Мы создаём идеальные команды для вашего бизнеса.\n\n"
        "Выберите интересующий раздел:"
    )


def text_about() -> str:
    return (
        f"📋 *О {COMPANY_NAME}*\n\n"
        f"*{COMPANY_NAME}* — профессиональное агентство по подбору "
        "и управлению персоналом для мероприятий любого масштаба.\n\n"
        "🔹 *Наша миссия:*\n"
        "Освободить вас от организационных хлопот и обеспечить "
        "безупречную работу команды на каждом этапе события.\n\n"
        "🔹 *Наши направления:*\n"
        "• Хелперы (event assistants)\n"
        "• Гардеробщики\n"
        "• Парковщики\n"
        "• Промоутеры и хостес\n"
        "• Супервайзеры / тимлидеры\n\n"
        "🔹 *Цифры:*\n"
        "• 1500+ обученных сотрудников в базе\n"
        "• 500+ успешных проектов\n"
        "• 97% довольных клиентов\n"
        "• 85% клиентов обращаются повторно\n\n"
        f"🌐 *Сайт:* {WEBSITE_URL}"
    )


def text_advantages() -> str:
    return (
        "⭐ *Наши преимущества*\n\n"
        "✅ *Большой пул проверенных специалистов*\n"
        "В базе более 1 500 обученных сотрудников. Подберём команду за 24 часа.\n\n"
        "✅ *Строгий отбор и обучение*\n"
        "Из 10 кандидатов отбираем 1–2 лучших. Проводим инструктаж перед проектом.\n\n"
        "✅ *Полный цикл «под ключ»*\n"
        "Подбор, обучение, логистика, координация, контроль качества, отчётность.\n\n"
        "✅ *Гибкость и масштабируемость*\n"
        "Работаем с проектами любого масштаба — от локальной акции до федеральной кампании.\n\n"
        "✅ *Прозрачные условия*\n"
        "Фиксированная стоимость без скрытых платежей.\n\n"
        "✅ *Гарантия замены*\n"
        "Оперативно заменим сотрудника в течение 2 часов без доплат.\n\n"
        "✅ *Комплексное оснащение*\n"
        "Брендированная униформа, промоматериалы, средства связи."
    )


def text_how_we_work() -> str:
    return (
        "🔄 *Как мы работаем*\n\n"
        "1️⃣ *Консультация*\n"
        "Обсуждаем цели, формат и детали мероприятия. Срок подготовки КП — до 24 часов.\n\n"
        "2️⃣ *Подбор команды*\n"
        "Формируем группу специалистов с нужным опытом. Согласовываем график и униформу.\n\n"
        "3️⃣ *Подготовка*\n"
        "Проводим брифинг и репетицию: знакомим персонал с продуктом и стандартами бренда.\n\n"
        "4️⃣ *Реализация*\n"
        "Сотрудники работают под контролем супервайзера. Вы получаете обратную связь и фотоотчёты.\n\n"
        "5️⃣ *Отчётность*\n"
        "Предоставляем итоговый отчёт в течение 48 часов после завершения проекта."
    )


def text_contact_manager() -> str:
    return (
        "📞 *Связаться с менеджером*\n\n"
        "Выберите удобный способ связи:\n\n"
        f"• *Telegram:* {CONTACT_TELEGRAM}\n"
        f"• *Телефон:* {CONTACT_PHONE}\n"
        f"• *Email:* {CONTACT_EMAIL}\n\n"
        "⏰ Время работы: ежедневно с 9:00 до 21:00"
    )


def text_join_team() -> str:
    return (
        "👥 *Работа в PROMOSTAFF AGENCY*\n\n"
        "Мы всегда в поиске активных и ответственных людей!\n\n"
        "📌 *Открытые вакансии:*\n"
        "• Хелперы (event assistants)\n"
        "• Гардеробщики\n"
        "• Парковщики\n"
        "• Промоутеры / Хостес\n"
        "• Супервайзеры\n\n"
        "Выберите действие:"
    )


def text_requirements() -> str:
    return (
        "📋 *Требования к кандидатам*\n\n"
        "✅ Возраст от 18 лет\n"
        "✅ Гражданство РФ / РБ / Казахстан\n"
        "✅ Ответственность и пунктуальность\n"
        "✅ Опрятный внешний вид\n"
        "✅ Грамотная речь\n\n"
        "*Для некоторых позиций:*\n"
        "• Наличие медкнижки\n"
        "• Опыт работы в event-сфере\n"
        "• Знание английского языка"
    )


def text_vacancies() -> str:
    return (
        "📂 *Открытые вакансии и ставки*\n\n"
        "🔹 *Хелпер* — от 6 000 ₽/смена\n"
        "Навигация, логистика, поддержка\n\n"
        "🔹 *Гардеробщик* — от 7 500 ₽/смена\n"
        "Обслуживание гардероба, учёт вещей\n\n"
        "🔹 *Парковщик* — от 7 500 ₽/смена\n"
        "Организация парковки, управление потоками\n\n"
        "🔹 *Промоутер* — от 7 500 ₽/смена\n"
        "Презентация продуктов, раздача материалов\n\n"
        "🔹 *Хостес* — от 8 000 ₽/смена\n"
        "Работа с гостями, регистрация\n\n"
        "🔹 *Супервайзер* — от 12 000 ₽/смена\n"
        "Координация команды, контроль"
    )


def message_main_menu() -> dict[str, Any]:
    return {"text": text_welcome(), "format": "markdown", "attachments": main_menu_keyboard()}


def message_for_static_payload(payload: str) -> dict[str, Any] | None:
    p = (payload or "").strip()
    if p in FLOW_PAYLOADS or p.startswith(POS_PREFIX):
        return None
    if p == "about":
        return {"text": text_about(), "format": "markdown", "attachments": about_keyboard()}
    if p == "advantages":
        return {"text": text_advantages(), "format": "markdown", "attachments": advantages_keyboard()}
    if p == "how_we_work":
        return {"text": text_how_we_work(), "format": "markdown", "attachments": how_we_work_keyboard()}
    if p == "contact_manager":
        return {"text": text_contact_manager(), "format": "markdown", "attachments": contact_keyboard()}
    if p == "join_team":
        return {"text": text_join_team(), "format": "markdown", "attachments": join_team_keyboard()}
    if p == "requirements":
        return {"text": text_requirements(), "format": "markdown", "attachments": back_to_main_keyboard()}
    if p == "vacancies":
        return {"text": text_vacancies(), "format": "markdown", "attachments": vacancies_keyboard()}
    return None
