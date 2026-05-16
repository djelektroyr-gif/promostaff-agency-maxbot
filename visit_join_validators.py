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
    if not re.fullmatch(r"\d{10}", s):
        return False
    series = s[:4]
    num = s[4:]
    if series[:2] in ("00", "99"):
        return False
    return num != "000000"


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


JOIN_EMAIL_MAX_LEN = 120
JOIN_BANK_NAME_MAX_LEN = 200
_CORR_ACCOUNT_SKIP_TOKENS = frozenset(
    ("нет", "no", "none", "—", "-", "пропустить", "skip", "не указан", "не указано")
)
_RE_JOIN_EMAIL = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


def normalize_snils_digits(text: str) -> str:
    return re.sub(r"\D", "", (text or "").strip())


def snils_checksum_valid(d11: str) -> bool:
    if len(d11) != 11 or not d11.isdigit():
        return False
    if d11 == "0" * 11 or d11[:9] == "000000000":
        return False
    s = sum(int(d11[i]) * (9 - i) for i in range(9))
    r = s % 101
    if r == 100:
        r = 0
    return int(d11[9:11]) == r


def normalize_snils_display(text: str) -> str:
    d = normalize_snils_digits(text)
    if len(d) != 11:
        return (text or "").strip()
    return f"{d[:3]}-{d[3:6]}-{d[6:9]} {d[9:]}"


def validate_join_snils(text: str) -> bool:
    d = normalize_snils_digits(text)
    return len(d) == 11 and snils_checksum_valid(d)


def validate_join_contact_email(text: str) -> str | None:
    s = (text or "").strip().lower()
    if not s or len(s) > JOIN_EMAIL_MAX_LEN:
        return None
    if not _RE_JOIN_EMAIL.match(s):
        return None
    return s


def normalize_bank_account_20(text: str) -> str:
    return re.sub(r"\D", "", (text or "").strip())


def validate_gph_bik(text: str) -> bool:
    d = re.sub(r"\D", "", (text or "").strip())
    return len(d) == 9 and d.isdigit()


def validate_gph_settlement_account(text: str) -> bool:
    d = normalize_bank_account_20(text)
    return len(d) == 20 and d.isdigit()


def parse_gph_corr_account_optional(text: str) -> str | None:
    raw = (text or "").strip().lower()
    if raw in _CORR_ACCOUNT_SKIP_TOKENS:
        return ""
    d = normalize_bank_account_20(text)
    if len(d) == 20 and d.isdigit():
        return d
    return None


def validate_gph_bank_name(text: str) -> bool:
    s = (text or "").strip()
    return bool(s) and len(s) <= JOIN_BANK_NAME_MAX_LEN


def validate_passport_issued_by(text: str) -> bool:
    s = (text or "").strip()
    if len(s) < 3 or len(s) > 240:
        return False
    if not re.search(r"[\u0410-\u042f\u0430-\u044fA-Za-z]", s):
        return False
    low = s.lower()
    for w in _PROFANITY_SUBSTRINGS:
        if w in low:
            return False
    return True


def validate_passport_issue_date(issue: date, *, birth: date | None, today: date) -> bool:
    if issue > today:
        return False
    if issue.year < 1997:
        return False
    if birth is not None and issue < birth:
        return False
    return True


def validate_registration_address(text: str) -> bool:
    s = (text or "").strip()
    if len(s) < 8 or len(s) > 500:
        return False
    if not re.search(r"[\u0410-\u042f\u0430-\u044fA-Za-z]", s):
        return False
    low = s.lower()
    for w in _PROFANITY_SUBSTRINGS:
        if w in low:
            return False
    return True


def join_metro_followup_needed(city_raw: str) -> bool:
    s = (city_raw or "").strip().lower()
    if not s:
        return False
    if "нижний" in s and "новгород" in s:
        return True
    needles = (
        "москва",
        "moscow",
        "санкт",
        "петербург",
        "спб",
        "питер",
        "новосибирск",
        "екатеринбург",
        "казань",
        "самара",
    )
    return any(n in s for n in needles)


def validate_join_work_city(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 2 or len(t) > 120:
        return False
    if not re.search(r"[\u0410-\u044fA-Za-z]", t):
        return False
    low = t.lower()
    for w in _PROFANITY_SUBSTRINGS:
        if w in low:
            return False
    return True


def validate_join_metro_station_text(text: str) -> tuple[bool, str]:
    t = (text or "").strip()
    if not t:
        return False, "Напишите станцию/линию или нажмите «Пропустить»."
    if len(t) > 120:
        return False, "Сократите текст (максимум 120 символов)."
    if not re.search(r"[\u0410-\u044fA-Za-z0-9]", t):
        return False, "Нужен осмысленный ответ (буквы или цифры)."
    low = t.lower()
    for w in _PROFANITY_SUBSTRINGS:
        if w in low:
            return False, "Уберите недопустимые выражения."
    return True, ""


def validate_join_portfolio_https_url(url: str) -> bool:
    s = (url or "").strip()
    if not s.lower().startswith("https://"):
        return False
    return len(s) <= 2048
