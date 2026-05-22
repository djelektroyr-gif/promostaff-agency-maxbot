# Копия канона promostaff-agency-bot/professions_data.py (анкета join).
# При смене каталога в TG — обновлять этот файл 1-в-1 (категории, slug, тексты).
from __future__ import annotations

from enum import Enum


class ProfessionCategory(str, Enum):
    MAIN = "main"
    CREATIVE = "creative"


PROFESSION_CATEGORY_LABEL_RU: dict[str, str] = {
    ProfessionCategory.MAIN.value: "Основной персонал",
    ProfessionCategory.CREATIVE.value: "Творческий персонал",
}

# Архивные category из старого MAX/TG — только отображение.
PROFESSION_CATEGORY_LABEL_LEGACY_RU: dict[str, str] = {
    "tech": "Технический персонал (архив)",
    "admin": "Административный персонал (архив)",
}

# Категории, которые больше не показываем в кнопках (старые callback в чате).
LEGACY_PROFESSION_CATEGORY_ALIASES: dict[str, str] = {
    "tech": ProfessionCategory.MAIN.value,
    "admin": ProfessionCategory.MAIN.value,
}

# (emoji, title, slug)
PROFESSION_BY_CATEGORY: dict[ProfessionCategory, list[tuple[str, str, str]]] = {
    ProfessionCategory.MAIN: [
        ("📢", "Промоутер", "promoter"),
        ("👩‍💼", "Хостес", "hostess"),
        ("🧥", "Гардеробщик", "wardrobe"),
        ("🎭", "Аниматор", "animator"),
        ("👷", "Хелпер", "helper"),
        ("📦", "Грузчик", "loader"),
        ("🍽️", "Официант", "waiter"),
        ("🚐", "Водитель", "driver"),
        ("🛡️", "Охранник", "security"),
        ("🚗", "Парковщик", "parking"),
        ("👨‍💼", "Супервайзер", "supervisor"),
    ],
    ProfessionCategory.CREATIVE: [
        ("🎧", "DJ", "dj"),
        ("📷", "Фотограф", "photographer"),
        ("🎬", "Видеограф", "videographer"),
        ("🎨", "Декоратор", "decorator"),
        ("🎤", "Ведущий", "host"),
    ],
}

LEGACY_PROFESSION_SLUG_TITLE_RU: dict[str, str] = {
    "pm": "Менеджер проекта",
    "coordinator": "Координатор",
    "cleaner": "Уборщик",
    "dishwasher": "Мойщик посуды",
    "courier": "Курьер",
}

PROFESSION_SLUG_TO_TITLE: dict[str, str] = {}
for _cat, items in PROFESSION_BY_CATEGORY.items():
    for _e, title, slug in items:
        PROFESSION_SLUG_TO_TITLE[slug] = title
for _slug, _title in LEGACY_PROFESSION_SLUG_TITLE_RU.items():
    PROFESSION_SLUG_TO_TITLE.setdefault(_slug, _title)


def resolve_profession_category_token(raw: str) -> str | None:
    """Нормализует prof_cat:* / архив tech|admin → main|creative."""
    s = (raw or "").strip().lower()
    if s.startswith("professioncategory."):
        s = s.split(".", 1)[-1]
    if s in LEGACY_PROFESSION_CATEGORY_ALIASES:
        return LEGACY_PROFESSION_CATEGORY_ALIASES[s]
    try:
        return ProfessionCategory(s).value
    except ValueError:
        return None


UNIFORM_REQUIREMENTS_TEXT = (
    "📋 *Требования к форме*\n\n"
    "📢 *Промоутер* — чистая одежда в деловом стиле (белый верх, тёмный низ).\n\n"
    "👩‍💼 *Хостес* — единая форма (часто даёт работодатель).\n\n"
    "🍽️ *Официант, повар* — спецодежда (обычно от работодателя).\n\n"
    "🎭 *Аниматор* — костюм персонажа (от работодателя).\n\n"
    "👷 *Хелпер* — аккуратный деловой или спортивный стиль по брифу.\n\n"
    "💡 _Своя подходящая форма — плюс при отборе на часть проектов._"
)


EXPERIENCE_RATING_TABLE = (
    "\n\nСтартовый уровень в системе задаётся по заявленному стажу и проверяется при модерации. "
    "Указывайте достоверный опыт — несоответствия выявляются на верификации."
)


def visit_vacancy_display_rows() -> list[tuple[str, str, str]]:
    """Паритет professions_data.visit_vacancy_display_rows — каталог для доски вакансий."""
    out: list[tuple[str, str, str]] = []
    _fallback = "Описание появится позже."
    for _cat, items in PROFESSION_BY_CATEGORY.items():
        for em, title, slug in items:
            out.append((slug, f"{em} {title}", _fallback))
    return out


def classify_open_vacancy_position_to_slug(position: str) -> str | None:
    """Свободный текст кампании → slug каталога (как в TG)."""
    s = (position or "").strip()
    if not s:
        return None
    low = s.lower()
    best_slug = None
    best_len = 0
    for slug, title in PROFESSION_SLUG_TO_TITLE.items():
        tl = title.strip().lower()
        if len(tl) >= 2 and tl in low and len(title) >= best_len:
            best_slug = slug
            best_len = len(title)
    return best_slug
