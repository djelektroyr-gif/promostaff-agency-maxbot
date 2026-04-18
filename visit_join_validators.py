# Синхронно с promostaff-agency-bot/join_anketa_utils.py (возраст 16–50, парсинг даты).
from __future__ import annotations

import os
import re
from datetime import date

JOIN_ANKETA_AGE_TEST_REFERENCE_TODAY = date(2026, 4, 17)


def age_check_reference_date() -> date:
    raw = (os.environ.get("JOIN_ANKETA_AGE_REFERENCE_DATE") or "").strip()
    if raw:
        return date.fromisoformat(raw)
    return date.today()


def parse_birth_date(text: str) -> date | None:
    t = (text or "").strip()
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", t)
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def validate_birth_date_16_50(bd: date, today: date) -> bool:
    age = today.year - bd.year - ((today.month, today.day) < (bd.month, bd.day))
    return 16 <= age <= 50


_PROFANITY_SUBSTRINGS = frozenset(
    (
        "хуй",
        "пизд",
        "ебан",
        "ебёт",
        "ебат",
        "бля",
        "сука",
        "муда",
    )
)


def validate_join_full_name(name: str) -> bool:
    if not name or not str(name).strip():
        return False
    s = str(name).strip()
    if re.search(r"\d", s):
        return False
    low = s.lower()
    for w in _PROFANITY_SUBSTRINGS:
        if w in low:
            return False
    pattern = r"^[\u0410-\u042f\u0430-\u044f\u0401\u0451A-Za-z\-\s']+$"
    if not re.match(pattern, s):
        return False
    words = s.split()
    return len(words) >= 2


def validate_join_phone(phone: str) -> str | None:
    clean = re.sub(r"\D", "", phone or "")
    if len(clean) == 11 and clean[0] in ("7", "8"):
        return "+7" + clean[1:]
    if len(clean) == 10 and clean[0] == "9":
        return "+7" + clean
    return None


def validate_inn_digits(text: str) -> bool:
    d = re.sub(r"\D", "", (text or "").strip())
    return len(d) in (10, 12)


def validate_height_cm(text: str) -> int | None:
    t = (text or "").strip()
    if t == "0":
        return 0
    if not re.fullmatch(r"\d+", t):
        return None
    v = int(t)
    if 150 <= v <= 210:
        return v
    return None


def validate_weight_kg(text: str) -> int | None:
    t = (text or "").strip()
    if t == "0":
        return 0
    if not re.fullmatch(r"\d+", t):
        return None
    v = int(t)
    if 45 <= v <= 120:
        return v
    return None


def validate_shoe_size(text: str) -> int | None:
    t = (text or "").strip()
    if t == "0":
        return 0
    if not re.fullmatch(r"\d+", t):
        return None
    v = int(t)
    if 35 <= v <= 48:
        return v
    return None


def validate_passport_series_number(text: str) -> bool:
    s = (text or "").strip().replace(" ", "")
    return bool(re.fullmatch(r"\d{10}", s))


def normalize_passport_series_number(text: str) -> str:
    s = re.sub(r"\D", "", (text or "").strip())
    if len(s) == 10:
        return f"{s[:4]} {s[4:]}"
    return (text or "").strip()


def validate_medbook_expiry(text: str) -> date | None:
    return parse_birth_date(text)


def experience_stars_from_choice(callback_data: str) -> tuple[str, int]:
    mapping = {
        "exp_lt1": ("Меньше года", 1),
        "exp_1_3": ("1–3 года", 2),
        "exp_gt3": ("Более 3 лет", 3),
    }
    return mapping.get(callback_data or "", ("", 0))


def experience_tag_from_stars(stars: int) -> str:
    return {1: "junior", 2: "middle", 3: "senior"}.get(stars, "unknown")
