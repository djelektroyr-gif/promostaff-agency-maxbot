# Синхронно с promostaff-agency-bot/join_anketa_catalog.py
from __future__ import annotations

from enum import Enum


class ProfessionCategory(str, Enum):
    MAIN = "main"
    TECH = "tech"
    CREATIVE = "creative"
    ADMIN = "admin"


# (emoji, title, slug)
PROFESSION_BY_CATEGORY: dict[ProfessionCategory, list[tuple[str, str, str]]] = {
    ProfessionCategory.MAIN: [
        ("📢", "Промоутер", "promoter"),
        ("👩‍💼", "Хостес", "hostess"),
        ("🎭", "Аниматор", "animator"),
        ("👷", "Хелпер", "helper"),
        ("📦", "Грузчик", "loader"),
        ("🍽️", "Официант", "waiter"),
    ],
    ProfessionCategory.TECH: [
        ("🚐", "Водитель", "driver"),
        ("🛡️", "Охранник", "security"),
        ("🧹", "Уборщик", "cleaner"),
        ("🧼", "Мойщик посуды", "dishwasher"),
        ("🚗", "Парковщик", "parking"),
        ("📦", "Курьер", "courier"),
    ],
    ProfessionCategory.CREATIVE: [
        ("🎧", "DJ", "dj"),
        ("📷", "Фотограф", "photographer"),
        ("🎬", "Видеограф", "videographer"),
        ("🎨", "Декоратор", "decorator"),
        ("🎤", "Ведущий", "host"),
    ],
    ProfessionCategory.ADMIN: [
        ("👨‍💼", "Супервайзер", "supervisor"),
        ("📋", "Менеджер проекта", "pm"),
        ("🗂️", "Координатор", "coordinator"),
    ],
}

PROFESSION_SLUG_TO_TITLE: dict[str, str] = {}
for _cat, items in PROFESSION_BY_CATEGORY.items():
    for _e, title, slug in items:
        PROFESSION_SLUG_TO_TITLE[slug] = title


UNIFORM_REQUIREMENTS_TEXT = (
    "*Требования к форме*\n\n"
    "| Роль | Форма |\n"
    "|------|-------|\n"
    "| Промоутер | Чистая одежда в деловом стиле (белый верх, тёмный низ) |\n"
    "| Хостес | Единая форма (часто предоставляется работодателем) |\n"
    "| Официант, повар | Спецодежда (предоставляется работодателем) |\n"
    "| Аниматор | Костюм персонажа (предоставляется работодателем) |\n"
    "| Хелпер | Аккуратный деловой или спортивный стиль по брифу |\n\n"
    "💡 _Если у вас есть своя форма, это преимущество при отборе на некоторые проекты._"
)


EXPERIENCE_RATING_TABLE = (
    "\n\n*Расчёт начального рейтинга:*\n"
    "```\n"
    "Опыт        | База | + за анкету | Итого\n"
    "------------+------+-------------+-------\n"
    "Меньше года | 1⭐  | до +1⭐     | до 2⭐\n"
    "1–3 года    | 2⭐  | до +1⭐     | до 3⭐\n"
    "Более 3 лет | 3⭐  | до +1⭐     | до 4⭐\n"
    "```"
)
