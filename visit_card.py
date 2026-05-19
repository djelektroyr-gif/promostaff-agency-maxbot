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
    TBANK_LK_URL,
    TERMS_OF_SERVICE_URL,
    WEBSITE_URL,
    contact_telegram_url,
    contact_whatsapp_url,
)
from max_attachments import cb_btn, inline_keyboard, link_btn
from visit_join_anketa_catalog import (
    PROFESSION_BY_CATEGORY,
    PROFESSION_SLUG_TO_TITLE,
    ProfessionCategory,
    UNIFORM_REQUIREMENTS_TEXT,
)

# Пэйлоады, которые обрабатывает visit_flows (не статичное редактирование одного сообщения).
FLOW_PAYLOADS = frozenset(
    {
        "calculate",
        "ask_manager",
        "fill_anketa",
        "join_team",
        "requirements",
        "vacancies",
        "join_proceed_anketa",
        "prof_add_another",
        "prof_done",
        "prof_edit_reset",
        "main_menu",
        "visit_public_menu",
        "back_to_main",
        "back",
        "none",
        "consent_client_visit_accept",
        "confirm_client_visit_yes",
        "confirm_client_visit_edit",
    }
)
VAC_PREFIX = "vac_apply_"

# Синхронно с promostaff-agency-bot/keyboards.py — VACANCY_DISPLAY (текст вакансий).
_VACANCY_CATALOG: list[tuple[str, str, str]] = [
    ("helper", "👷 Хелпер", "Навигация, поддержка гостей, логистика на площадке"),
    ("loader", "📦 Грузчик", "Погрузка, перенос, работа с грузом"),
    ("promoter", "📢 Промоутер", "Презентация продукта, раздача материалов"),
    ("hostess", "👩‍💼 Хостес", "Встреча гостей, регистрация, сопровождение"),
    ("animator", "🎭 Аниматор", "Работа в образе, развлечение гостей, детские и family-зоны"),
    ("barista", "☕ Бариста", "Приготовление кофе и напитков на точке"),
    ("bartender", "🍸 Бармен", "Барная стойка, классические и авторские напитки"),
    ("waiter", "🍽️ Официант", "Сервировка, обслуживание гостей в зале"),
    ("cashier", "💰 Кассир", "Расчёт с гостями, вежливое обслуживание на кассе"),
    ("chef_head", "👨‍🍳 Шеф-повар", "Горячий цех, сложные блюда и координация кухни на площадке"),
    ("cook", "🍳 Повар", "Приготовление блюд по технологическим картам"),
    ("dishwasher", "🧼 Мойщик посуды", "Мойка посуды и поддержание порядка на кухне"),
    ("cleaner", "🧹 Уборщик", "Поддержание чистоты в зонах для гостей и персонала"),
    ("cloakroom", "🧥 Гардеробщик", "Приём и выдача верхней одежды"),
    ("security", "🛡️ Охранник", "Контроль доступа, порядок и безопасность на объекте"),
    ("parking", "🚗 Парковщик", "Организация парковки, встреча авто"),
    ("driver", "🚐 Водитель", "Трансфер и служебные перевозки по маршруту"),
    ("shuttle_driver", "🚌 Шаттл-водитель", "Перевозка гостей на шаттлах между точками"),
    ("supervisor", "👨‍💼 Супервайзер", "Координация команды на площадке"),
]


def is_visit_flow_payload(p: str) -> bool:
    """Колбэки сценария (order/join), не статические экраны."""
    if p in FLOW_PAYLOADS or p.startswith(VAC_PREFIX):
        return True
    if p.startswith(("prof_cat:", "prof_pick:", "prof_custom:")):
        return True
    if p in (
        "prof_back",
        "uniform_info",
        "uniform_own_yes",
        "uniform_own_no",
        "medbook_yes",
        "medbook_no",
        "trips_yes",
        "trips_no",
        "join_review_ok",
        "join_review_edit",
        "gender_m",
        "gender_f",
    ):
        return True
    if p.startswith("size_"):
        return True
    if p.startswith(("pos_", "jpos_", "exp_", "quick_", "jp_", "shift_", "docs_", "prio_")):
        return True
    if (p or "").startswith("tax_"):
        return True
    if p in (
        "positions_done",
        "sv_add",
        "sv_skip",
        "confirm_order",
        "edit_order",
        "order_mode_quick",
        "order_mode_cp",
        "order_mode_listing",
        "client_quote_listing",
        "client_quote_quick",
        "client_quote_cp",
        "client_visit_menu",
        "confirm_listing_order",
        "edit_listing_order",
        "join_tbank_proceed",
        "join_tbank_reg_yes",
        "join_tbank_reg_no",
        "join_tbank_reg_retry",
        "clrf:start",
        "clrf:ack",
        "contact_ch_call",
        "contact_ch_max",
        "contact_ch_mail",
        "cp_brief_yes",
        "cp_brief_no",
        "cp_ch_call",
        "cp_ch_msg",
        "cp_ch_mail",
        "confirm_cp_order",
        "edit_cp_order",
        "cp_flow_back",
        "order_flow_back",
        "client_cabinet",
        "submit_join",
        "submit_join_anketa",
        "portfolio_done",
        "consent_order_accept",
        "consent_join_accept",
        "join_proceed_anketa",
        "consent_question_accept",
        "join_terms_agree",
        "join_terms_decline",
        "join_portfolio_none",
        "join_portfolio_pdf",
        "join_portfolio_url",
        "join_metro_skip",
        "client_reg_projects",
        "client_reg_orders",
        "client_reg_settings",
        "client_reg_web",
        "open_web_cabinet",
        "worker_reg_profile",
        "worker_reg_shifts",
        "worker_reg_payments",
        "worker_reg_beacon",
    ):
        return True
    return False


def client_pre_erp_pending_keyboard() -> list[dict]:
    """Заказчик зарегистрирован, админ ещё не подтвердил — как _pre_erp_client_keyboard(quotes_enabled=False)."""
    return inline_keyboard(
        [
            [cb_btn("📞 Связаться с менеджером", "contact_manager")],
            [cb_btn("🏠 Меню визитки", "visit_public_menu")],
        ]
    )


def client_registered_main_menu_keyboard(*, quotes_enabled: bool = True) -> list[dict]:
    """Меню заказчика после регистрации — REGISTRATION_AND_POST_MENU_SPEC.md §5."""
    rows: list[list[dict]] = [
        [cb_btn("📂 Мои проекты", "client_reg_projects")],
        [cb_btn("📜 История заказов", "client_reg_orders")],
        [cb_btn("⚙️ Настройки", "client_reg_settings")],
        [cb_btn("🌐 Кабинет на сайте", "open_web_cabinet")],
    ]
    if quotes_enabled:
        rows.append([cb_btn("📋 Заказать проект", "client_quote_quick")])
        rows.append([cb_btn("📄 Заказать КП", "client_quote_cp")])
        rows.append([cb_btn("📣 Разместить объявление", "client_quote_listing")])
    rows.append([cb_btn("🏠 Меню визитки", "visit_public_menu")])
    return inline_keyboard(rows)


def worker_pending_verification_keyboard() -> list[dict]:
    """Исполнитель на проверке — только связь с менеджером."""
    return inline_keyboard([[cb_btn("📞 Связаться с менеджером", "contact_manager")]])


def worker_clarification_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("✏️ Дозаполнить запрошенные данные", "clrf:start")],
            [cb_btn("✅ Отправить на проверку снова", "clrf:ack")],
            [cb_btn("📞 Связаться с менеджером", "contact_manager")],
            [cb_btn("🏠 Меню визитки", "visit_public_menu")],
        ]
    )


def worker_registered_main_menu_keyboard() -> list[dict]:
    """Меню исполнителя после регистрации — REGISTRATION_AND_POST_MENU_SPEC.md §6."""
    rows: list[list[dict]] = [
        [cb_btn("👤 Мои данные", "worker_reg_profile")],
        [cb_btn("📅 Мои смены", "worker_reg_shifts")],
        [cb_btn("💳 Мои выплаты", "worker_reg_payments")],
        [cb_btn("📍 Маяк", "worker_reg_beacon")],
        [cb_btn("🌐 Кабинет на сайте", "open_web_cabinet")],
        [cb_btn("🏠 Меню визитки", "visit_public_menu")],
    ]
    return inline_keyboard(rows)


def join_terms_keyboard() -> list[dict]:
    """Перед селфи — §4.3 REGISTRATION_AND_POST_MENU_SPEC."""
    return inline_keyboard(
        [
            [link_btn("📄 Политика конфиденциальности", PRIVACY_POLICY_URL)],
            [link_btn("📄 Пользовательское соглашение", TERMS_OF_SERVICE_URL)],
            [cb_btn("✅ Согласен", "join_terms_agree")],
            [cb_btn("❌ Не согласен", "join_terms_decline")],
        ]
    )


def main_menu_keyboard() -> list[dict]:
    # Паритет с Telegram keyboards.visit_card_keyboard: компактное корневое меню;
    # преимущества, кейсы, вакансии и расчёт — внутри «О нас» (about_keyboard).
    rows: list[list[dict]] = [
        [cb_btn("📋 О нас", "about")],
        [cb_btn("💼 Меню заказчика", "client_visit_menu")],
        [cb_btn("🛠 Меню исполнителя", "join_team")],
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


def cp_flow_back_keyboard() -> list[dict]:
    """Назад по сценарию КП без главного меню."""
    return inline_keyboard([[cb_btn("⬅️ Назад", "cp_flow_back")]])


def cp_step_keyboard() -> list[dict]:
    """Шаги КП без кнопки «Назад» (паритет с Telegram-визиткой)."""
    return inline_keyboard([])


def order_flow_back_keyboard() -> list[dict]:
    """Назад по срочному расчёту (в т.ч. с ввода даты)."""
    return inline_keyboard([[cb_btn("⬅️ Назад", "order_flow_back")]])


def advantages_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("📋 К разделу «О нас»", "about")],
            [cb_btn("🏠 В главное меню", "main_menu")],
        ]
    )


def about_keyboard() -> list[dict]:
    """Паритет с Telegram keyboards.about_section_keyboard."""
    return inline_keyboard(
        [
            [cb_btn("⭐ Преимущества", "advantages")],
            [cb_btn("🔄 Как мы работаем", "how_we_work")],
            [cb_btn("💬 Отзывы", "reviews")],
            [cb_btn("📁 Кейсы", "cases")],
            [link_btn("🌐 Наш сайт", WEBSITE_URL)],
            [cb_btn("📂 Вакансии", "vacancies")],
            [cb_btn("💼 Меню заказчика", "client_visit_menu")],
            [cb_btn("🛠 Меню исполнителя", "join_team")],
            [cb_btn("🏠 В главное меню", "main_menu")],
        ]
    )


def how_we_work_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("📋 К разделу «О нас»", "about")],
            [cb_btn("🏠 В главное меню", "main_menu")],
        ]
    )


def cases_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("🏛️ Московская неделя интерьера", "case_mwid")],
            [cb_btn("🌍 Форум БРИКС", "case_brics")],
            [cb_btn("🎡 Фестиваль Портал 2030", "case_portal")],
            [cb_btn("📦 Федеральный ритейл", "case_retail")],
            [cb_btn("💬 Отзывы", "reviews")],
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


# Единый текст с Telegram handlers/visit_public.py JOIN_CANDIDATE_REQUIREMENTS_MARKDOWN
JOIN_CANDIDATE_REQUIREMENTS_MARKDOWN = (
    "*Требования к кандидатам*\n\n"
    "Возраст от 18 лет\n"
    "Гражданство РФ / РБ / Казахстан\n"
    "Ответственность и пунктуальность\n"
    "Опрятный внешний вид\n"
    "Грамотная речь\n\n"
    "*Для некоторых позиций:*\n"
    "• Наличие медкнижки\n"
    "• Опыт работы в event-сфере\n"
    "• Знание английского языка"
)


def role_entry_keyboard(role: str) -> list[dict]:
    r = "client" if (role or "").strip().lower() == "client" else "worker"
    return inline_keyboard(
        [
            [cb_btn("✅ Уже регистрировался", f"visit_entry_returning:{r}")],
            [cb_btn("🆕 Регистрируюсь впервые", f"visit_entry_new:{r}")],
            [cb_btn("⬅️ Назад", "main_menu")],
        ]
    )


def role_not_found_keyboard(role: str) -> list[dict]:
    """После «номер не найден» — сразу на регистрацию или повтор ввода."""
    r = "client" if (role or "").strip().lower() == "client" else "worker"
    return inline_keyboard(
        [
            [cb_btn("🆕 Регистрируюсь впервые", f"visit_entry_new:{r}")],
            [cb_btn("📞 Указать другой номер", f"visit_entry_returning:{r}")],
            [cb_btn("⬅️ В главное меню", "main_menu")],
        ]
    )


def join_team_intro_keyboard() -> list[dict]:
    """Паритет keyboards.join_team_intro_keyboard — без вакансий на первом экране."""
    return inline_keyboard(
        [
            [cb_btn("📝 Заполнить анкету", "fill_anketa")],
            [cb_btn("📋 Требования к кандидатам", "requirements")],
            [cb_btn("⬅️ Назад", "back_to_main")],
        ]
    )


def join_team_back_keyboard() -> list[dict]:
    return inline_keyboard([[cb_btn("🛠 К меню исполнителя", "join_team")]])


def join_team_keyboard() -> list[dict]:
    return join_team_intro_keyboard()


def join_anketa_invite_keyboard() -> list[dict]:
    """После согласия ПДн: приглашение заполнить анкету (до выбора трека)."""
    return inline_keyboard(
        [
            [cb_btn("📝 Заполнить анкету", "join_proceed_anketa")],
        ]
    )


def profession_categories_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("👷 Основной персонал", f"prof_cat:{ProfessionCategory.MAIN}")],
            [cb_btn("🔧 Технический персонал", f"prof_cat:{ProfessionCategory.TECH}")],
            [cb_btn("🎨 Креативный персонал", f"prof_cat:{ProfessionCategory.CREATIVE}")],
            [cb_btn("👔 Административный персонал", f"prof_cat:{ProfessionCategory.ADMIN}")],
            [cb_btn("🏠 Главное меню", "main_menu")],
        ]
    )


def profession_summary_keyboard(*, edit_mode: bool = False) -> list[dict]:
    """Паритет join_anketa profession_summary_keyboard."""
    done_label = "✅ К подтверждению анкеты" if edit_mode else "➡️ Дальше — ФИО и анкета"
    rows: list[list[dict]] = [
        [cb_btn("➕ Добавить ещё профессию", "prof_add_another")],
        [cb_btn(done_label, "prof_done")],
    ]
    if edit_mode:
        rows.append([cb_btn("🔁 Очистить и выбрать заново", "prof_edit_reset")])
    return inline_keyboard(rows)


def profession_list_keyboard(cat: ProfessionCategory) -> list[dict]:
    rows: list[list[dict]] = []
    for emoji, title, slug in PROFESSION_BY_CATEGORY[cat]:
        rows.append([cb_btn(f"{emoji} {title}", f"prof_pick:{slug}")])
    rows.append([cb_btn("➕ Добавить новую профессию", f"prof_custom:{cat.value}")])
    rows.append([cb_btn("🔙 Назад к категориям", "prof_back")])
    rows.append([cb_btn("🏠 Главное меню", "main_menu")])
    return inline_keyboard(rows)


def experience_level_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("👶 Меньше года — 1⭐", "exp_lt1")],
            [cb_btn("👨‍💼 1–3 года — 2⭐", "exp_1_3")],
            [cb_btn("👨‍🎓 Более 3 лет — 3⭐", "exp_gt3")],
            [cb_btn("🏠 Главное меню", "main_menu")],
        ]
    )


def gender_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("🙋‍♂️ Мужской", "gender_m")],
            [cb_btn("🙋‍♀️ Женский", "gender_f")],
            [cb_btn("🏠 Главное меню", "main_menu")],
        ]
    )


def clothing_size_keyboard() -> list[dict]:
    sizes = ["XS", "S", "M", "L", "XL", "XXL"]
    row1 = [cb_btn(f"👕 {sizes[i]}", f"size_{sizes[i]}") for i in range(3)]
    row2 = [cb_btn(f"👕 {sizes[i]}", f"size_{sizes[i]}") for i in range(3, 6)]
    return inline_keyboard(
        [
            row1,
            row2,
            [cb_btn("🏠 Главное меню", "main_menu")],
        ]
    )


def uniform_after_info_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("✅ У меня есть подходящая одежда для работы", "uniform_own_yes")],
            [cb_btn("❌ Мне нужна форма от работодателя", "uniform_own_no")],
            [cb_btn("🏠 Главное меню", "main_menu")],
        ]
    )


def uniform_entry_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("ℹ️ Уточнить требования к форме", "uniform_info")],
            [cb_btn("✅ У меня есть подходящая одежда для работы", "uniform_own_yes")],
            [cb_btn("❌ Мне нужна форма от работодателя", "uniform_own_no")],
            [cb_btn("🏠 Главное меню", "main_menu")],
        ]
    )


def medbook_has_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("✅ Есть", "medbook_yes")],
            [cb_btn("❌ Нет", "medbook_no")],
            [cb_btn("🏠 Главное меню", "main_menu")],
        ]
    )


def trips_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("✅ Готов(а)", "trips_yes")],
            [cb_btn("❌ Не готов(а)", "trips_no")],
            [cb_btn("🏠 Главное меню", "main_menu")],
        ]
    )


def join_review_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("✅ Данные верны, отправить на проверку", "join_review_ok")],
            [cb_btn("✏️ Изменить данные", "join_review_edit")],
        ]
    )


def text_uniform_requirements() -> str:
    return UNIFORM_REQUIREMENTS_TEXT


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


def text_tax_status_intro() -> str:
    return (
        "💼 *НАЛОГОВЫЙ СТАТУС*\n\n"
        "*Выберите ваш налоговый статус:*\n"
        "Статус влияет на размер выплат и способ перечисления.\n\n"
        "ℹ️ Если вы ещё не зарегистрированы как самозанятый, вы можете сделать это, "
        "выбрав соответствующий пункт."
    )


def text_tax_fl_disclaimer() -> str:
    return (
        "Вы выбрали статус *физическое лицо*. Мы обязаны предупредить: налог *13% НДФЛ* "
        "(удерживается платформой). Вы можете оформить самозанятость.\n\n"
        "✨ *Преимущества самозанятости:*\n"
        "• Ниже налог (*6%* вместо *13%*)\n"
        "• Не нужно сдавать декларацию в рамках режима НПД\n"
        "• Легальный доход с подтверждением в приложении «Мой налог»\n"
        "• Возможность работать с юрлицами и ИП\n"
    )


def tbank_self_employed_invite_md() -> str:
    u = (TBANK_LK_URL or "").strip()
    if not u:
        return ""
    return (
        "\n\n🔗 *Т-Банк Бизнес (самозанятые):*\n"
        f"[Перейти по ссылке из вашего кабинета]({u})\n"
        "_Оформление в банке не заменяет регистрацию в «Мой налог» и загрузку справки в анкету — "
        "это отдельный шаг для выплат через Т-Банк, если он вам нужен._"
    )


def tbank_self_employed_invite_plain() -> str:
    if not (TBANK_LK_URL or "").strip():
        return ""
    return (
        "✅ *Справка принята.*\n\n"
        "🏦 *Кабинет Т-Банка для выплат (самозанятый)*\n\n"
        "Нажмите *«Открыть кабинет Т-Банка»* ниже, при необходимости завершите регистрацию, "
        "затем *«Далее»*.\n\n"
        "_Оформление в банке не заменяет регистрацию в «Мой налог» и загрузку справки в анкету — "
        "это отдельный шаг для выплат через Т-Банк._"
    )


def tbank_register_confirm_prompt_md() -> str:
    return (
        "*Регистрация в кабинете Т-Банка*\n\n"
        "Нажмите кнопку подтверждения ниже *только если вы действительно завершили регистрацию "
        "самозанятого* в личном кабинете Т-Банка для выплат.\n\n"
        "_Недостоверное подтверждение недопустимо: сведения проверяет менеджер._\n\n"
        "_Это ваше заявление в боте, а не автоматическая проверка банком._"
    )


def tbank_register_must_complete_md() -> str:
    return (
        "*Анкета на паузе: нужен кабинет Т-Банка*\n\n"
        "Следующие шаги анкеты откроются после регистрации самозанятого в ЛК Т-Банка.\n\n"
        "1. *«Открыть кабинет Т-Банка»* — доделайте регистрацию.\n"
        "2. *«Завершил(а) в ЛК — к подтверждению»* — вернётесь к подтверждению."
    )


def tbank_cabinet_gate_keyboard() -> list[dict] | None:
    u = (TBANK_LK_URL or "").strip()
    if not u:
        return None
    return inline_keyboard(
        [
            [link_btn("🏦 Открыть кабинет Т-Банка", u)],
            [cb_btn("➡️ Далее", "join_tbank_proceed")],
            [cb_btn("🏠 Главное меню", "main_menu")],
        ]
    )


def tbank_register_confirm_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("Подтверждаю: завершил(а) регистрацию НПД в ЛК Т-Банка", "join_tbank_reg_yes")],
            [cb_btn("❌ Нет, ещё нет", "join_tbank_reg_no")],
            [cb_btn("🏠 Главное меню", "main_menu")],
        ]
    )


def tbank_register_blocked_keyboard() -> list[dict] | None:
    u = (TBANK_LK_URL or "").strip()
    if not u:
        return tbank_register_confirm_keyboard()
    return inline_keyboard(
        [
            [link_btn("🏦 Открыть кабинет Т-Банка", u)],
            [cb_btn("🔁 Завершил(а) в ЛК — к подтверждению", "join_tbank_reg_retry")],
            [cb_btn("🏠 Главное меню", "main_menu")],
        ]
    )


def text_tax_self_help() -> str:
    return (
        "*Что нужно сделать:*\n\n"
        "1. Скачайте приложение *«Мой налог»*:\n"
        "• [App Store](https://apps.apple.com/ru/app/%D0%BC%D0%BE%D0%B9-%D0%BD%D0%B0%D0%BB%D0%BE%D0%B3/id1437518854?l=en-GB)\n"
        "• [Google Play](https://play.google.com/store/apps/details?id=com.gnivts.selfemployed&hl=ru&pli=1)\n"
        "• [RuStore](https://www.rustore.ru/catalog/app/com.gnivts.selfemployed)\n\n"
        "2. Зарегистрируйтесь по паспорту и ИНН.\n"
        "3. Подтвердите регистрацию в приложении.\n"
        "4. Скачайте *справку о постановке на учёт* и пришлите её нам кнопкой *«📎 Загрузить справку»* "
        "(документ или чёткое фото).\n\n"
        "После загрузки вы будете отмечены в системе как самозанятый (данные попадут в панель)."
    ) + tbank_self_employed_invite_md()


def join_tax_status_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("👤 Физическое лицо", "tax_fl")],
            [cb_btn("💼 Самозанятый", "tax_se")],
            [cb_btn("🏢 Индивидуальный предприниматель", "tax_ip")],
            [cb_btn("🔗 Помощь в оформлении самозанятости", "tax_help")],
            [cb_btn("🔙 Назад к дате рождения", "tax_back_bd")],
            [cb_btn("🏠 Главное меню", "main_menu")],
        ]
    )


def tax_fl_followup_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("🔗 Помощь в оформлении самозанятости", "tax_help")],
            [cb_btn("➡️ Продолжить как 👤 Физическое лицо", "tax_fl_go")],
            [cb_btn("🔙 Назад к выбору статуса", "tax_back_status")],
            [cb_btn("🏠 Главное меню", "main_menu")],
        ]
    )


def tax_se_actions_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("📎 Загрузить справку", "tax_upload_cert")],
            [cb_btn("✅ Отправить на проверку", "tax_se_send")],
            [cb_btn("🔙 Назад к выбору статуса", "tax_back_status")],
            [cb_btn("🏠 Главное меню", "main_menu")],
        ]
    )


def tax_ip_actions_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("📎 Загрузить выписку", "tax_upload_cert")],
            [cb_btn("✅ Отправить на проверку", "tax_ip_send")],
            [cb_btn("🔙 Назад к выбору статуса", "tax_back_status")],
            [cb_btn("🏠 Главное меню", "main_menu")],
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


def join_portfolio_menu_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("Нет портфолио", "join_portfolio_none")],
            [cb_btn("Отправлю PDF", "join_portfolio_pdf")],
            [cb_btn("Пришлю ссылку (https)", "join_portfolio_url")],
            [cb_btn("🏠 Главное меню", "main_menu")],
        ]
    )


def work_metro_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("⏭ Пропустить", "join_metro_skip")],
            [cb_btn("🏠 Главное меню", "main_menu")],
        ]
    )


def join_portfolio_keyboard() -> list[dict]:
    return join_portfolio_menu_keyboard()


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
    for pos in CLIENT_POSITIONS:
        c = int(sel.get(pos, 0) or 0)
        label = f"{pos} ({c})" if c else pos
        rows.append([cb_btn(label, f"pos_{pos}")])
    rows.append([cb_btn("Готово", "positions_done")])
    rows.append([cb_btn("Назад", "back_to_main")])
    return inline_keyboard(rows)


def order_mode_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("⚡ Срочный расчёт в боте", "order_mode_quick")],
            [cb_btn("📄 Запросить коммерческое предложение", "order_mode_cp")],
            [cb_btn("📣 Разместить объявление", "order_mode_listing")],
            [cb_btn("В главное меню", "main_menu")],
        ]
    )


def listing_confirm_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("✅ Отправить заявку", "confirm_listing_order")],
            [cb_btn("✏️ Изменить", "edit_listing_order")],
            [cb_btn("В главное меню", "main_menu")],
        ]
    )


def order_contact_channel_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("📞 Звонок", "contact_ch_call")],
            [cb_btn("💬 Сообщение в MAX", "contact_ch_max")],
            [cb_btn("📧 Email", "contact_ch_mail")],
            [cb_btn("В главное меню", "main_menu")],
        ]
    )


def order_quickstart_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("⚡ Срочный проект (24ч)", "quick_urgent")],
            [cb_btn("🏢 Выставка", "quick_expo")],
            [cb_btn("🎤 Корпоратив", "quick_corp")],
            [cb_btn("✍️ Ввести свой вариант", "quick_custom")],
            [cb_btn("В главное меню", "main_menu")],
        ]
    )


def cp_brief_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("Да, есть бриф / ТЗ", "cp_brief_yes")],
            [cb_btn("Нет", "cp_brief_no")],
        ]
    )


def cp_channel_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("📞 Звонок", "cp_ch_call")],
            [cb_btn("💬 Сообщение в мессенджере", "cp_ch_msg")],
            [cb_btn("✉️ Email", "cp_ch_mail")],
        ]
    )


def cp_confirm_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("Отправить заявку на КП", "confirm_cp_order")],
            [cb_btn("Изменить данные", "edit_cp_order")],
            [cb_btn("Отменить", "main_menu")],
        ]
    )


def supervisor_offer_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("Добавить в расчёт", "sv_add")],
            [cb_btn("Без супервайзера", "sv_skip")],
        ]
    )


def experience_keyboard() -> list[dict]:
    rows = [[cb_btn(exp, f"exp_{exp}")] for exp in EXPERIENCE_OPTIONS]
    rows.append([cb_btn("🏠 В главное меню", "main_menu")])
    return inline_keyboard(rows)


def submit_join_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("Отправить анкету", "submit_join_anketa")],
            [cb_btn("👥 К работе в команде", "join_team")],
            [cb_btn("🏠 В главное меню", "main_menu")],
        ]
    )


def order_confirm_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("Отправить заявку на расчёт", "confirm_order")],
            [cb_btn("Изменить данные", "edit_order")],
            [cb_btn("Отменить", "main_menu")],
        ]
    )


def client_reg_confirm_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("✅ Данные верны, завершить регистрацию", "confirm_client_visit_yes")],
            [cb_btn("✏️ Заполнить заново", "confirm_client_visit_edit")],
            [cb_btn("⬅️ В меню", "main_menu")],
        ]
    )


def consent_gate_keyboard(flow: str) -> list[dict]:
    callbacks = {
        "order": "consent_order_accept",
        "join": "consent_join_accept",
        "question": "consent_question_accept",
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


def vacancies_list_keyboard() -> list[dict]:
    """Список вакансий — паритет с Telegram keyboards.vacancies_list_keyboard."""
    rows: list[list[dict]] = []
    catalog = list(_VACANCY_CATALOG)
    for i in range(0, len(catalog), 2):
        chunk = catalog[i : i + 2]
        row = [cb_btn(chunk[0][1], f"vac_view_{chunk[0][0]}")]
        if len(chunk) > 1:
            row.append(cb_btn(chunk[1][1], f"vac_view_{chunk[1][0]}"))
        rows.append(row)
    rows.append([cb_btn("📋 К разделу «О нас»", "about")])
    rows.append([cb_btn("🏠 Главное меню визитки", "main_menu")])
    return inline_keyboard(rows)


def vacancy_detail_keyboard(slug: str) -> list[dict]:
    return inline_keyboard(
        [
            [cb_btn("📝 Заполнить анкету", f"vac_apply_{slug}")],
            [cb_btn("⬅️ К списку вакансий", "vacancies")],
            [cb_btn("🏠 Главное меню", "main_menu")],
        ]
    )


def vacancies_keyboard() -> list[dict]:
    return vacancies_list_keyboard()


def text_welcome() -> str:
    # Синхронно с Telegram handlers._main_menu_text() и главной https://promostaff-agency.ru/
    # В MAX картинка в приветствии — только через публичный URL (задайте BRAND_LOGO_URL после выкладки того же PNG, что в assets/logo.png).
    tail = f"\n\n[Логотип]({BRAND_LOGO_URL})" if BRAND_LOGO_URL else ""
    return (
        f"*{COMPANY_NAME}*\n\n"
        "Ваш надёжный партнёр в подборе временного персонала.\n\n"
        "Мы не просто подбираем сотрудников —\n"
        "мы создаём идеальные команды для вашего бизнеса.\n\n"
        "Выберите раздел в меню ниже 👇"
        f"{tail}"
    )


def text_about() -> str:
    return (
        "*PROMOSTAFF-AGENCY*\n\n"
        "Мы технологичное агентство по подбору и управлению временным персоналом для ивент-сферы.\n\n"
        "Мы не подбираем людей «на глаз». Мы построили собственную систему отбора, оценки и управления, "
        "которая исключает человеческий фактор на этапе найма.\n\n"
        "*Как мы работаем:*\n\n"
        "— Автоматизированный процесс приёма: от заявки до выхода сотрудника\n"
        "— Жёсткая верификация: документы, опыт, навыки, фото, видео-интервью\n"
        "— Оценка по критериям под конкретный тип мероприятия\n"
        "— Цифровой профиль каждого специалиста\n\n"
        "Результат: вы получаете не «кого-то, кто свободен сегодня», а проверенного сотрудника с понятными компетенциями.\n\n"
        "*Направления:*\n"
        "Хелперы, гардеробщики, парковщики, промоутеры, хостес, промо-модели, супервайзеры.\n\n"
        "*Наши ключевые проекты:*\n"
        "Московская неделя интерьера и дизайна, Форум БРИКС «Облачный город», фестиваль «Портал».\n\n"
        "*Нишевое преимущество:*\n"
        "Сильнее всего там, где важны управляемость на площадке, скорость замены и единый стандарт сервиса — "
        "retail, BTL, выставки и корпоративы среднего и крупного масштаба.\n\n"
        "*Цифры:*\n"
        "Более 1 500 специалистов в системе · 500+ проектов · 97% довольных клиентов"
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
        "*Как мы работаем*\n\n"
        "Пять этапов. Прозрачно, измеримо, под контролем.\n\n"
        "*1. Заявка и консультация*\n"
        "_Вы оставляете заявку: даты, формат, количество человек, задачи и бюджет.\n"
        "Мы анализируем специфику мероприятия.\n"
        "Срок: коммерческое предложение до 24 часов._\n\n"
        "*2. Формирование команды*\n"
        "_Отбираем сотрудников под ваш сценарий.\n"
        "Согласовываем график, униформу, оснащение.\n"
        "Срок: обычно 1–3 рабочих дня._\n\n"
        "*3. Подготовка и брифинг*\n"
        "Проводим инструктаж: продукт, сценарий, стандарты бренда, зоны ответственности.\n"
        "При необходимости — репетиция на площадке или онлайн.\n\n"
        "*4. Реализация на площадке*\n"
        "Работа под контролем супервайзера. Онлайн-координация, быстрые замены.\n"
        "Промежуточная обратная связь и фотоотчёты.\n\n"
        "*5. Итоговая отчётность*\n"
        "_Закрывающие документы, фото- и видеофиксация, оценка по KPI "
        "(при необходимости, стоимость по запросу).\n"
        "Срок: в течение 48 часов после завершения проекта._"
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
        f"*Меню исполнителя · {COMPANY_NAME}*\n\n"
        "Ищем ответственных специалистов под задачи агентства.\n\n"
        "*Направления:* хелперы, гардеробщики, парковщики, промоутеры, хостес, супервайзеры.\n\n"
        "👇 *Дальше:*"
    )


def text_requirements() -> str:
    return JOIN_CANDIDATE_REQUIREMENTS_MARKDOWN


def vacancies_summary_markdown() -> str:
    return (
        "*Открытые вакансии*\n\n"
        f"{COMPANY_NAME} всегда в поиске надёжных специалистов для задач агентства.\n\n"
        + JOIN_CANDIDATE_REQUIREMENTS_MARKDOWN
    )


def text_vacancies() -> str:
    return vacancies_summary_markdown()


def vacancy_detail_markdown(slug: str) -> str | None:
    from config import order_hourly_rates

    for key, title_em, desc in _VACANCY_CATALOG:
        if key != slug:
            continue
        title_plain = PROFESSION_SLUG_TO_TITLE.get(slug) or (
            title_em.split(" ", 1)[-1] if " " in title_em else title_em
        )
        base_rub = order_hourly_rates().get(title_plain)
        if base_rub is not None:
            br_fmt = f"{int(base_rub):,}".replace(",", " ")
            rate_lines = (
                f"\n\n💰 *Ориентир:* {br_fmt} ₽/ч при уровне подбора *0* (база каталога).\n\n"
                "_Итоговая ставка считается индивидуально: к базе добавляются надбавки по вашему рейтингу — "
                "он формируется по анкете и по проектам при работе с агентством._"
            )
        else:
            rate_lines = (
                "\n\n_Итоговая ставка считается индивидуально по вашему рейтингу "
                "(данные анкеты и проекты с агентством)._"
            )
        return f"*{title_em}*\n\n{desc}{rate_lines}"
    return None

def text_faq() -> str:
    return (
        "*Частые вопросы*\n\n"
        "*Как быстро вы подбираете персонал?*\n"
        "_В базе — более 1 500 обученных сотрудников; подбор команды — от 24 часов, в срочных случаях быстрее по согласованию._\n\n"
        "*Каких специалистов вы можете предоставить?*\n"
        "_Хелперы, гардеробщики, парковщики, промоутеры, хостес и промо-модели, супервайзеры / тимлидеры — под задачу мероприятия._\n\n"
        "*Как происходит контроль персонала?*\n"
        "_Координация на площадке, контроль качества в реальном времени, при необходимости — фото- и видеофиксация; итоговый отчёт после проекта._\n\n"
        "*Вы работаете с документами и налогами?*\n"
        "_Условия оформления и оплаты фиксируем в договоре и коммерческом предложении под ваш формат проекта._\n\n"
        "*Какие гарантии вы предоставляете?*\n"
        "_При необходимости организуем замену сотрудника в течение 2 часов без доплат — в рамках согласованных условий._\n\n"
        "*Как оставить заявку?*\n"
        "_«Заказать расчёт» в меню или «Связаться с менеджером» — подготовим КП в течение 24 часов._\n\n"
        "*У вас есть собственная система управления персоналом?*\n"
        "_Да. Мы автоматизировали процесс приёма, оценки и контроля:\n"
        "Цифровой профиль каждого сотрудника с верификацией по 12 критериям\n"
        "Онлайн-координация на площадке с геометкой выхода\n"
        "Быстрые замены через систему в реальном времени\n"
        "Автоматическая фото- и видеофиксация с привязкой к смене\n"
        "Это не «табличка в Excel». Это технологическая платформа, которая исключает человеческий фактор на этапе найма и контроля._"
    )


def text_reviews() -> str:
    return (
        "*Отзывы клиентов*\n\n"
        "_«Организовывали масштабный отраслевой форум на 1 500 участников — требовалось 40 хостес и 20 хелперов. "
        "Персонал подобрали быстро, все были обучены заранее… Форум прошёл безупречно.»_\n"
        "*— Анна Смирнова, руководитель отдела маркетинга, «ТехноИннова»*\n\n"
        "_«Для трёхдневного фестиваля нужно было 120 хелперов на разные зоны… Агентство справилось на 100 %. "
        "Замену одного сотрудника решили за 40 минут без сбоев.»_\n"
        "*— Дмитрий Орлов, продюсер фестиваля «Света»*\n\n"
        "_«Федеральная промоакция в 20 торговых центрах… 80 промоутеров FMCG, единые стандарты, ежедневная отчётность. "
        "Очень довольны — всё чётко и прозрачно.»_\n"
        "*— Алексей Петров, бренд-менеджер, ВкусВилл*"
    )


def text_cases() -> str:
    return (
        "*Ключевые проекты*\n\n"
        "🏛️ *Московская неделя интерьера и дизайна*\n"
        "Крупнейшая B2B-выставка в России. Работаем с первого сезона — 6 выставок подряд. До 120 человек в смену. Ноль сорванных смен.\n\n"
        "🌍 *Форум БРИКС «Облачный город»*\n"
        "Международный форум с делегатами стран БРИКС. Эксклюзивный оператор по персоналу. 100+ сотрудников. Без единого сбоя.\n\n"
        "🎡 *Фестиваль «Портал 2030»*\n"
        "Массовое городское событие с десятками тысяч гостей. До 150+ хелперов в смену. Работаем в пике без потери качества.\n\n"
        "📦 *Федеральный промо-запуск (ритейл)*\n"
        "Одновременный старт в 30+ точках. Единый стандарт коммуникации. Фото- и видеоотчётность по каждой точке.\n\n"
        "Подробнее 👇"
    )


def text_case_mwid() -> str:
    return (
        "*Московская неделя интерьера и дизайна*\n"
        "Крупнейшая в России B2B-выставка в сегменте интерьера и дизайна.\n"
        "Площадка, где ведущие производители, дизайнеры и архитекторы представляют новые коллекции, заключают контракты и формируют тренды.\n\n"
        "*Наше присутствие:* с первого дня существования выставки.\n"
        "Все 6 сезонов подряд — без единого пропуска.\n\n"
        "*Объём работы:* до 120 человек в смену.\n"
        "*Кого закрывали:* хелперы, гардеробщики, логисты, контролёры входа.\n\n"
        "*Результат:* 100% своевременный выход. Ноль сорванных смен за 6 мероприятий.\n\n"
        "Когда выставка выросла в главную отраслевую площадку страны — её организаторы остались с нами."
    )


def text_case_brics() -> str:
    return (
        "*Форум БРИКС «Облачный город»*\n"
        "Международный форум с участием официальных делегатов стран БРИКС.\n"
        "Высший уровень протокола, аккредитации, безопасности.\n\n"
        "*Наша роль:* эксклюзивный оператор по временному персоналу.\n\n"
        "*Объём работы:* 100+ сотрудников.\n"
        "*Кого закрывали:* бэкстейдж, хелперы, парковщики, работа с делегатами.\n\n"
        "*Результат:* форум прошёл без единого сбоя по человеческому фактору."
    )


def text_case_portal() -> str:
    return (
        "*Фестиваль «Портал 2030»*\n"
        "Массовое городское событие с десятками тысяч гостей.\n"
        "Высокий трафик, десятки зон, сложная логистика — классический стресс-тест для любой команды.\n\n"
        "*Наш максимум:* 150+ хелперов в смену.\n\n"
        "*Зоны ответственности:* АХО, камера хранения, входные группы, мгновенные замены при выбытии.\n\n"
        "*Результат:* ни одной остановки работы зон по нашей вине.\n"
        "Работаем в пике без потери качества."
    )


def text_case_retail() -> str:
    return (
        "*Федеральный промо-запуск (ритейл)*\n"
        "Одновременный старт в 30+ точках.\n"
        "Единый стандарт коммуникации по всей сети.\n\n"
        "*Что сдали:* фото- и видеоотчётность по каждой точке. Без исключений.\n\n"
        "*Вывод:* масштаб не снижает качество контроля.\n"
        "Прозрачно, измеримо, тиражируемо."
    )


def message_main_menu() -> dict[str, Any]:
    return {
        "text": text_welcome(),
        "format": "markdown",
        "attachments": main_menu_keyboard(),
    }


def message_role_home(max_uid: int | None) -> dict[str, Any]:
    """Главный экран при старте и «домой»: кабинет заказчика/исполнителя по БД или публичная визитка."""
    from funnel_db import (
        WORKER_STATUS_CLARIFICATION,
        get_max_worker_display_name,
        has_max_active_executor_profile,
        is_max_visit_client_registered,
        is_max_visit_client_verified,
        is_max_visit_worker_verified,
    )
    from join_clarification_db import (
        CLARIFICATION_FLAG_LABELS_RU,
        get_max_join_clarification_context,
        get_max_worker_status,
    )

    if not max_uid:
        return message_main_menu()
    uid = int(max_uid)
    wk = is_max_visit_worker_verified(uid)
    if get_max_worker_status(uid) == WORKER_STATUS_CLARIFICATION:
        ctx = get_max_join_clarification_context(uid)
        lines = [
            "*Нужны уточнения по анкете*\n",
            "Менеджер запросил дозаполнение. Нажмите кнопку ниже и пришлите данные по очереди.\n",
        ]
        flags = ctx.get("flags") or []
        if flags:
            lines.append("*Что нужно:*")
            for c in flags:
                cc = str(c).strip().lower()
                lines.append(f"• {CLARIFICATION_FLAG_LABELS_RU.get(cc, cc)}")
        note = str(ctx.get("note") or "").strip()
        if note:
            lines.append(f"\n*Комментарий менеджера:*\n{note}")
        if not flags:
            lines.append(
                "\n_Если правки только в комментарии — нажмите «Отправить на проверку снова»._"
            )
        return {
            "text": "\n".join(lines),
            "format": "markdown",
            "attachments": worker_clarification_keyboard(),
        }
    exec_pending = bool(has_max_active_executor_profile(uid) and not wk)
    cl_verified = is_max_visit_client_verified(uid)
    cl_registered = is_max_visit_client_registered(uid)

    if wk:
        return {
            "text": (
                "*Главное меню исполнителя*\n\n"
                "Вы вошли как верифицированный исполнитель. "
                "Ниже — разделы профиля; публичное меню визитки — кнопка «Меню визитки»."
            ),
            "format": "markdown",
            "attachments": worker_registered_main_menu_keyboard(),
        }
    if exec_pending:
        fio = get_max_worker_display_name(uid)
        name_block = f"👤 *{fio}*\n\n" if fio else ""
        return {
            "text": (
                "*Анкета исполнителя на проверке*\n\n"
                f"{name_block}"
                "Вы уже отправили анкету. После подтверждения администратором откроются "
                "назначения на смены, выплаты и остальные разделы исполнителя.\n\n"
                "_Публичное меню визитки — только для гостей без профиля в системе._"
            ),
            "format": "markdown",
            "attachments": worker_pending_verification_keyboard(),
        }
    if cl_registered:
        if cl_verified:
            cap = (
                f"*Главное меню заказчика*\n\n"
                f"Вы вошли как зарегистрированный заказчик *{COMPANY_NAME}*.\n\n"
                "Профиль подтверждён. Заявки, расчёты и связь с менеджером — в меню ниже."
            )
            kb = client_registered_main_menu_keyboard(quotes_enabled=True)
        else:
            cap = (
                f"*Главное меню заказчика*\n\n"
                f"Регистрация принята. Данные проверяет администратор; после подтверждения "
                "откроются заявки на расчёт, запрос КП и раздел «История заказов».\n\n"
                "Пока можете написать менеджеру — кнопка ниже."
            )
            kb = client_pre_erp_pending_keyboard()
        return {"text": cap, "format": "markdown", "attachments": kb}
    return message_main_menu()


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
    # join_team, requirements, vacancies, vac_view_* — visit_flows (роли, тексты как в TG)
    if p == "faq":
        return {"text": text_faq(), "format": "markdown", "attachments": back_to_main_keyboard()}
    if p == "reviews":
        return {"text": text_reviews(), "format": "markdown", "attachments": back_to_main_keyboard()}
    if p == "cases":
        return {"text": text_cases(), "format": "markdown", "attachments": cases_keyboard()}
    if p == "case_mwid":
        return {"text": text_case_mwid(), "format": "markdown", "attachments": cases_keyboard()}
    if p == "case_brics":
        return {"text": text_case_brics(), "format": "markdown", "attachments": cases_keyboard()}
    if p == "case_portal":
        return {"text": text_case_portal(), "format": "markdown", "attachments": cases_keyboard()}
    if p == "case_retail":
        return {"text": text_case_retail(), "format": "markdown", "attachments": cases_keyboard()}
    return None
