"""
Визитка MAX — копия сценария PROMOSTAFF-AGENCY BOT (Telegram): keyboards.py + тексты из handlers.py.
Колбэки payload совпадают с callback_data в Telegram (about, main_menu, …).
"""
from __future__ import annotations

from typing import Any

from config import (
    APPLICANT_POSITIONS,
    CLIENT_POSITIONS,
    COMPANY_NAME,
    CONTACT_EMAIL,
    CONTACT_PHONE,
    CONTACT_TELEGRAM,
    EXPERIENCE_OPTIONS,
    PORTFOLIO_URL,
    WEBSITE_URL,
    contact_telegram_url,
    contact_whatsapp_url,
)
from max_attachments import cb_btn, inline_keyboard, link_btn

# Пэйлоады, которые обрабатывает visit_flows (не статичное редактирование одного сообщения).
FLOW_PAYLOADS = frozenset(
    {
        "calculate",
        "ask_manager",
        "fill_anketa",
        "main_menu",
        "back_to_main",
        "back",
        "none",
    }
)
VAC_PREFIX = "vac_apply_"


def is_visit_flow_payload(p: str) -> bool:
    """Колбэки сценария (order/join), не статические экраны."""
    if p in FLOW_PAYLOADS or p.startswith(VAC_PREFIX):
        return True
    if p.startswith(("o_", "jpos_", "exp_")):
        return True
    if p in ("staff_done", "sv_add", "sv_skip", "order_send", "order_edit", "submit_join"):
        return True
    return False


def main_menu_keyboard() -> list[dict]:
    # Тот же порядок и подписи, что в Telegram-визитке (без эмодзи в кнопках главного меню).
    rows: list[list[dict]] = [
        [cb_btn("Об агентстве", "about")],
        [cb_btn("Преимущества", "advantages")],
        [cb_btn("Как мы работаем", "how_we_work")],
        [cb_btn("Заказать расчёт", "calculate")],
        [cb_btn("Хочу в команду", "join_team")],
        [link_btn("Наш сайт", WEBSITE_URL)],
        [cb_btn("Отзывы", "reviews")],
        [cb_btn("FAQ", "faq")],
        [cb_btn("Связаться с менеджером", "contact_manager")],
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
            [cb_btn("💬 Отзывы", "reviews")],
            [cb_btn("⬅️ Назад", "back_to_main")],
            [cb_btn("🏠 В главное меню", "main_menu")],
        ]
    )


def about_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("⭐ Преимущества", "advantages")],
            [cb_btn("💰 Заказать расчёт", "calculate")],
            [cb_btn("💬 Отзывы", "reviews")],
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
    rows: list[list[dict]] = [
        [cb_btn(f"Телефон: {CONTACT_PHONE}", "contact_show_phone")],
        [link_btn("WhatsApp", contact_whatsapp_url())],
        [link_btn("Telegram", contact_telegram_url())],
        [cb_btn(f"Email: {CONTACT_EMAIL}", "contact_show_email")],
        [cb_btn("Написать менеджеру", "ask_manager")],
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


def join_applicant_pick_keyboard() -> list[dict]:
    rows: list[list[dict]] = []
    row: list[dict] = []
    for i, pos in enumerate(APPLICANT_POSITIONS[:12]):
        row.append(cb_btn(pos if len(pos) <= 30 else pos[:27] + "…", f"jpos_{i}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([cb_btn("Другое (введу текстом)", "jpos_other")])
    rows.append([cb_btn("🏠 В главное меню", "main_menu")])
    return inline_keyboard(rows)


def order_staff_keyboard(selected: dict[str, int] | None) -> list[dict]:
    sel = selected or {}
    rows: list[list[dict]] = []
    for i, pos in enumerate(CLIENT_POSITIONS):
        c = int(sel.get(pos, 0) or 0)
        label = f"{pos} ({c})" if c else pos
        rows.append([cb_btn(label, f"o_{i}")])
    rows.append([cb_btn("Готово", "staff_done")])
    rows.append([cb_btn("🏠 В главное меню", "main_menu")])
    return inline_keyboard(rows)


def supervisor_offer_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("Добавить в расчёт", "sv_add")],
            [cb_btn("Без супервайзера", "sv_skip")],
            [cb_btn("🏠 В главное меню", "main_menu")],
        ]
    )


def experience_keyboard() -> list[dict]:
    rows = [[cb_btn(exp, f"exp_{i}")] for i, exp in enumerate(EXPERIENCE_OPTIONS)]
    rows.append([cb_btn("🏠 В главное меню", "main_menu")])
    return inline_keyboard(rows)


def submit_join_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("Отправить анкету", "submit_join")],
            [cb_btn("👥 К работе в команде", "join_team")],
            [cb_btn("🏠 В главное меню", "main_menu")],
        ]
    )


def order_confirm_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("Отправить заявку на расчёт", "order_send")],
            [cb_btn("Изменить данные", "order_edit")],
            [cb_btn("🏠 В главное меню", "main_menu")],
        ]
    )


def vacancies_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("Хочу: Хелпер", "vac_apply_helper")],
            [cb_btn("Хочу: Грузчик", "vac_apply_loader")],
            [cb_btn("Хочу: Промоутер", "vac_apply_promoter")],
            [cb_btn("Хочу: Гардеробщик", "vac_apply_cloakroom")],
            [cb_btn("Хочу: Парковщик", "vac_apply_parking")],
            [cb_btn("Хочу: Хостес", "vac_apply_hostess")],
            [cb_btn("Хочу: Супервайзер", "vac_apply_supervisor")],
            [cb_btn("\u2b05\ufe0f \u041d\u0430\u0437\u0430\u0434", "join_team")],
            [cb_btn("\U0001f3e0 \u0412 \u0433\u043b\u0430\u0432\u043d\u043e\u0435 \u043c\u0435\u043d\u044e", "main_menu")],
        ]
    )


def text_welcome() -> str:
    return (
        f"*{COMPANY_NAME}*\n\n"
        "Ваш надёжный партнёр в подборе временного персонала.\n"
        "Мы создаём идеальные команды для вашего бизнеса.\n\n"
        "Выберите раздел в меню ниже:"
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
        "📂 *Открытые вакансии*\n\n"
        "🔹 *Хелпер* — навигация, поддержка гостей\n\n"
        "🔹 *Грузчик* — погрузка, перенос\n\n"
        "🔹 *Промоутер* — презентация\n\n"
        "🔹 *Гардеробщик* — гардероб\n\n"
        "🔹 *Парковщик* — парковка\n\n"
        "🔹 *Хостес* — встреча гостей, регистрация\n\n"
        "🔹 *Супервайзер* — координация на площадке"
    )

def text_faq() -> str:
    return (
        "*FAQ*\n\n"
        "*Как быстро вы подбираете персонал?*\n"
        "Обычно за 24–48 часов, в срочных случаях — быстрее по согласованию.\n\n"
        "*Работаете ли вы по всей России?*\n"
        "Да, организуем проекты в разных городах — уточните локацию при расчёте.\n\n"
        "*Что входит в стоимость?*\n"
        "Подбор, согласование состава, базовый инструктаж и координация на площадке; "
        "детали фиксируем в коммерческом предложении.\n\n"
        "*Можно ли заменить сотрудника?*\n"
        "Да, при необходимости организуем замену, условия обсуждаются по договорённости.\n\n"
        "*Как оставить заявку?*\n"
        "«Заказать расчёт» в меню или «Связаться с менеджером»."
    )


def text_reviews() -> str:
    return (
        "*Отзывы о нас*\n\n"
        "Мы много лет собираем команды для выставок, корпоративов, промо и крупных событий. "
        "Клиенты отмечают пунктуальность персонала, аккуратность на площадке и понятную коммуникацию "
        "с координаторами.\n\n"
        "Нам доверяют повторные запуски: чёткий бриф, быстрый отклик и спокойствие в день мероприятия — "
        "то, ради чего к нам приходят агентства и бренды."
    )


def message_main_menu() -> dict[str, Any]:
    return {"text": text_welcome(), "format": "markdown", "attachments": main_menu_keyboard()}


def message_for_static_payload(payload: str) -> dict[str, Any] | None:
    p = (payload or "").strip()
    if is_visit_flow_payload(p):
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
    if p == "faq":
        return {"text": text_faq(), "format": "markdown", "attachments": back_to_main_keyboard()}
    if p == "reviews":
        return {"text": text_reviews(), "format": "markdown", "attachments": back_to_main_keyboard()}
    return None
