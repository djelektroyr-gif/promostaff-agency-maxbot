"""
Визитка MAX — копия сценария PROMOSTAFF-AGENCY BOT (Telegram): keyboards.py + тексты из handlers.py.
Колбэки payload совпадают с callback_data в Telegram (about, main_menu, …).
"""
from __future__ import annotations

from typing import Any

from config import (
    APPLICANT_POSITIONS,
    BRAND_LOGO_URL,
    CLIENT_POSITIONS,
    COMPANY_NAME,
    CONTACT_EMAIL,
    CONTACT_PHONE,
    CONTACT_TELEGRAM,
    EXPERIENCE_OPTIONS,
    PRIVACY_POLICY_URL,
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
        "consent_client_visit_accept",
        "consent_worker_pro_accept",
        "confirm_client_visit_yes",
        "confirm_client_visit_edit",
    }
)
VAC_PREFIX = "vac_apply_"


def is_visit_flow_payload(p: str) -> bool:
    """Колбэки сценария (order/join), не статические экраны."""
    if p in FLOW_PAYLOADS or p.startswith(VAC_PREFIX):
        return True
    if p.startswith(("o_", "jpos_", "exp_", "quick_", "jp_", "shift_", "docs_", "prio_")):
        return True
    if p in (
        "staff_done",
        "sv_add",
        "sv_skip",
        "order_send",
        "order_edit",
        "submit_join",
        "portfolio_done",
        "consent_order_accept",
        "consent_join_accept",
        "consent_question_accept",
    ):
        return True
    return False


def main_menu_keyboard() -> list[dict]:
    # Главное меню: тот же порядок, что в Telegram; эмодзи — нативное «богатство» интерфейса MAX.
    rows: list[list[dict]] = [
        [cb_btn("📋 Об агентстве", "about")],
        [cb_btn("⭐ Преимущества", "advantages")],
        [cb_btn("🔄 Как мы работаем", "how_we_work")],
        [cb_btn("💰 Заказать расчёт", "calculate")],
        [cb_btn("👥 Хочу в команду", "join_team")],
        [link_btn("🌐 Наш сайт", WEBSITE_URL)],
        [cb_btn("💬 Отзывы", "reviews")],
        [cb_btn("📁 Кейсы", "cases")],
        [cb_btn("❓ FAQ", "faq")],
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
        [cb_btn("🧾 Шаблон брифа", "brief_template")],
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


def join_profile_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("🚀 С опытом в ивентах", "jp_exp")],
            [cb_btn("🌱 Начинающий", "jp_beginner")],
            [cb_btn("📅 Подработка по выходным", "jp_weekend")],
            [cb_btn("🎯 Сразу выбрать должность", "jp_direct")],
            [cb_btn("👥 К работе в команде", "join_team")],
            [cb_btn("🏠 В главное меню", "main_menu")],
        ]
    )


def join_shift_pref_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("🌤 Дневные смены", "shift_day")],
            [cb_btn("🌙 Ночные смены", "shift_night")],
            [cb_btn("🔄 Оба варианта", "shift_both")],
            [cb_btn("🏠 В главное меню", "main_menu")],
        ]
    )


def join_docs_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("📗 Медкнижка есть", "docs_med")],
            [cb_btn("🧾 Самозанятость", "docs_self")],
            [cb_btn("🏢 ИП", "docs_ip")],
            [cb_btn("📚 Оформлю при необходимости", "docs_later")],
            [cb_btn("🏠 В главное меню", "main_menu")],
        ]
    )


def join_portfolio_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("✅ Продолжить", "portfolio_done")],
            [cb_btn("🏠 В главное меню", "main_menu")],
        ]
    )


def join_priority_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("🔥 Да, хочу в приоритетный пул", "prio_yes")],
            [cb_btn("👌 Пока без приоритета", "prio_no")],
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


def order_quickstart_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("⚡ Срочный проект (24ч)", "quick_urgent")],
            [cb_btn("🏢 Выставка", "quick_expo")],
            [cb_btn("🎤 Корпоратив", "quick_corp")],
            [cb_btn("✍️ Ввести свой вариант", "quick_custom")],
            [cb_btn("🏠 В главное меню", "main_menu")],
        ]
    )


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


def client_reg_confirm_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("✅ Данные верны, завершить регистрацию", "confirm_client_visit_yes")],
            [cb_btn("✏️ Заполнить заново", "confirm_client_visit_edit")],
            [cb_btn("🏠 В главное меню", "main_menu")],
        ]
    )


def consent_gate_keyboard(flow: str) -> list[dict]:
    callbacks = {
        "order": "consent_order_accept",
        "join": "consent_join_accept",
        "question": "consent_question_accept",
        "worker_pro": "consent_worker_pro_accept",
        "client_visit": "consent_client_visit_accept",
    }
    cb = callbacks.get(flow, "main_menu")
    return inline_keyboard(
        [
            [link_btn("📄 Политика и согласие", PRIVACY_POLICY_URL)],
            [cb_btn("✅ Согласен с обработкой данных", cb)],
            [cb_btn("⬅️ Вернуться в меню", "main_menu")],
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
    # Синхронно с Telegram handlers._main_menu_text() и главной https://promostaff-agency.ru/
    # В MAX картинка в приветствии — только через публичный URL (задайте BRAND_LOGO_URL после выкладки того же PNG, что в assets/logo.png).
    tail = f"\n\n[Логотип]({BRAND_LOGO_URL})" if BRAND_LOGO_URL else ""
    return (
        f"*{COMPANY_NAME}*\n\n"
        "Ваш надёжный партнёр в подборе временного персонала. "
        "Мы не просто подбираем сотрудников — мы создаём идеальные команды для вашего бизнеса.\n\n"
        "Выберите раздел в меню ниже:"
        f"{tail}"
    )


def text_about() -> str:
    return (
        f"📋 *О {COMPANY_NAME}*\n\n"
        f"{COMPANY_NAME} специализируется на временном персонале для ивент-сферы: от единичных позиций "
        "до масштабных проектов с сотнями сотрудников. Помогаем организаторам закрывать кадры в срок.\n\n"
        "*Миссия:* освободить вас от организационных хлопот и обеспечить слаженную работу команды на каждом этапе события.\n\n"
        "*Направления:* хелперы, гардеробщики, парковщики, промоутеры, хостес и промо-модели, супервайзеры / тимлидеры.\n\n"
        "*Цифры с сайта:*\n"
        "• более 1 500 обученных специалистов в базе\n"
        "• 500+ успешных проектов\n"
        "• 97% довольных клиентов, 85% обращаются повторно\n"
        "• охват мероприятий — свыше 1 млн гостей ежегодно\n\n"
        f"Подробнее: {WEBSITE_URL}"
    )


def text_advantages() -> str:
    return (
        "⭐ *Наши преимущества*\n\n"
        "✅ *Большой пул проверенных специалистов*\n"
        "В базе — более 1 500 обученных сотрудников разных профилей; подбор команды — от 24 часов.\n\n"
        "✅ *Строгий отбор и обучение*\n"
        "Из 10 кандидатов отбираем 1–2 лучших; перед выходом — инструктаж по бренду и задачам мероприятия.\n\n"
        "✅ *Полный цикл «под ключ»*\n"
        "Подбор и обучение, логистика и координация на площадке, контроль качества, отчётность с фото- и видеофиксацией.\n\n"
        "✅ *Гибкость и масштабируемость*\n"
        "От локальной акции до федеральной кампании; оперативно наращиваем команду до 100+ человек.\n\n"
        "✅ *Прозрачные условия*\n"
        "Фиксированная стоимость за час/смену без скрытых платежей.\n\n"
        "✅ *Гарантия замены*\n"
        "При необходимости — замена в течение 2 часов без доплат (в рамках договора).\n\n"
        "✅ *Комплексное оснащение*\n"
        "Униформа, промоматериалы, рации и другое — по запросу."
    )


def text_how_we_work() -> str:
    return (
        "🔄 *Как мы работаем*\n\n"
        "*1. Консультация*\n"
        "Обсуждаем цели, формат и детали мероприятия, персонал и бюджет. Подготовка КП — до 24 часов.\n\n"
        "*2. Подбор команды*\n"
        "Формируем состав с нужным опытом; согласовываем график и униформу — обычно 1–3 рабочих дня.\n\n"
        "*3. Подготовка*\n"
        "Брифинг и репетиция: продукт, сценарий, стандарты бренда (от 2 до 8 часов в зависимости от задачи).\n\n"
        "*4. Реализация*\n"
        "Работа на площадке под контролем супервайзера; обратная связь и фотоотчёты каждые 3–4 часа в день события.\n\n"
        "*5. Отчётность*\n"
        "Итоговый документ — в течение 48 часов после завершения проекта."
    )


def text_contact_manager() -> str:
    return (
        "📞 *Связаться с менеджером*\n\n"
        "Выберите удобный канал связи — ответим в рабочее время.\n\n"
        f"• *Telegram:* {CONTACT_TELEGRAM}\n"
        f"• *Телефон:* {CONTACT_PHONE}\n"
        f"• *Email:* {CONTACT_EMAIL}\n\n"
        "⏰ Время работы: ежедневно с 9:00 до 21:00\n"
        "Для детального коммерческого предложения укажите задачу и сроки проекта."
    )


def text_brief_template() -> str:
    return (
        "*Шаблон брифа для расчёта*\n\n"
        "Скопируйте и заполните:\n\n"
        "1) Формат проекта:\n"
        "2) Город и площадка:\n"
        "3) Дата/период и время смены:\n"
        "4) Нужные роли и количество по каждой роли:\n"
        "5) Требования к персоналу (внешний вид, опыт, язык):\n"
        "6) Нужен ли супервайзер/тимлидер:\n"
        "7) Контактное лицо и удобное время связи:\n"
        "8) Комментарии по проекту:\n\n"
        "_Чем точнее бриф, тем быстрее и точнее финальное КП._"
    )


def text_join_team() -> str:
    return (
        f"👥 *Работа в {COMPANY_NAME}*\n\n"
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
        "*Частые вопросы*\n\n"
        "*Как быстро вы подбираете персонал?*\n"
        "В базе — более 1 500 обученных сотрудников; подбор команды — от 24 часов, в срочных случаях быстрее по согласованию.\n\n"
        "*Каких специалистов вы можете предоставить?*\n"
        "Хелперы, гардеробщики, парковщики, промоутеры, хостес и промо-модели, супервайзеры / тимлидеры — под задачу мероприятия.\n\n"
        "*Как происходит контроль персонала?*\n"
        "Координация на площадке, контроль качества в реальном времени, при необходимости — фото- и видеофиксация; итоговый отчёт после проекта.\n\n"
        "*Вы работаете с документами и налогами?*\n"
        "Условия оформления и оплаты фиксируем в договоре и коммерческом предложении под ваш формат проекта.\n\n"
        "*Какие гарантии вы предоставляете?*\n"
        "При необходимости организуем замену сотрудника в течение 2 часов без доплат — в рамках согласованных условий.\n\n"
        "*Как оставить заявку?*\n"
        "«Заказать расчёт» в меню или «Связаться с менеджером» — подготовим КП в течение 24 часов."
    )


def text_reviews() -> str:
    return (
        "*Отзывы клиентов*\n\n"
        "«Организовывали масштабный отраслевой форум на 1 500 участников — требовалось 40 хостес и 20 хелперов. "
        "Персонал подобрали быстро, все были обучены заранее… Форум прошёл безупречно.»\n"
        "— Анна Смирнова, руководитель отдела маркетинга, «ТехноИннова»\n\n"
        "«Для трёхдневного фестиваля нужно было 120 хелперов на разные зоны… Агентство справилось на 100 %. "
        "Замену одного сотрудника решили за 40 минут без сбоев.»\n"
        "— Дмитрий Орлов, продюсер фестиваля «Света»\n\n"
        "«Федеральная промоакция в 20 торговых центрах… 80 промоутеров FMCG, единые стандарты, ежедневная отчётность. "
        "Очень довольны — всё чётко и прозрачно.»\n"
        "— Алексей Петров, бренд-менеджер, ВкусВилл\n\n"
        "Полные тексты — на сайте в разделе отзывов."
    )


def text_cases() -> str:
    return (
        f"*Опыт и масштабы ({COMPANY_NAME})*\n\n"
        "Фрагменты реальных задач с сайта promostaff-agency.ru:\n\n"
        "*Форум и конференции*\n"
        "Крупный отраслевой форум, навигация и регистрация — десятки хостес и хелперов, супервайзеры на площадке.\n\n"
        "*Фестивали и многодневные события*\n"
        "Сотни хелперов по зонам, брендированная униформа, слаженная логистика и замены без простоя.\n\n"
        "*Федеральные промо и retail*\n"
        "Параллельный запуск в десятках точек, единые стандарты коммуникации, отчётность по договорённости.\n\n"
        "Подробные кейсы и услуги — на сайте."
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
    if p == "brief_template":
        return {"text": text_brief_template(), "format": "markdown", "attachments": contact_keyboard()}
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
    if p == "cases":
        return {"text": text_cases(), "format": "markdown", "attachments": back_to_main_keyboard()}
    return None
