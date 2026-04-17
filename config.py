"""Конфиг из окружения (Timeweb / локальный .env). Дефолты — как в PROMOSTAFF-AGENCY BOT (Telegram)."""
from __future__ import annotations

import os
import re
from pathlib import Path


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    v = _env(name).lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


def _env_int_list(name: str) -> list[int]:
    raw = _env(name)
    if not raw:
        return []
    out: list[int] = []
    for part in raw.replace(";", ",").split(","):
        p = part.strip()
        if not p:
            continue
        try:
            out.append(int(p))
        except ValueError:
            continue
    return out


MAX_TOKEN = _env("MAX_TOKEN")

# Опционально: Postgres для воронки и напоминаний (как funnel_* в PRO).
DATABASE_URL = _env("DATABASE_URL")
# Как в promostaff-bot/config.py — одна версия согласия для users.pd_consent_version и регистрации MAX/Telegram.
PD_CONSENT_VERSION = _env("PD_CONSENT_VERSION") or "2026-04-10-v1"
# Кнопка Т-Банка в шагах самозанятости (как в PRO); только через env.
TBANK_LK_URL = _env("TBANK_LK_URL") or _env("PROMOSTAFF_TBANK_PORTAL_URL")
FUNNEL_REMINDERS_ENABLED = _env_bool("FUNNEL_REMINDERS_ENABLED", False)
FUNNEL_REMINDERS_INTERVAL_SEC = _env_int("FUNNEL_REMINDERS_INTERVAL_SEC", 600)

# Как в Desktop PROMOSTAFF-AGENCY BOT/config.py (можно переопределить в Timeweb).
COMPANY_NAME = _env("COMPANY_NAME") or "PROMOSTAFF-AGENCY"
WEBSITE_URL = _env("WEBSITE_URL") or "https://promostaff-agency.ru"
_BASE_DIR = Path(__file__).resolve().parent
LOGO_PNG_PATH = _BASE_DIR / "assets" / "logo.png"
# Публичный HTTPS URL логотипа (для MAX и опционально в тексте). Файл в репо: assets/logo.png — см. assets/README.txt
BRAND_LOGO_URL = _env("BRAND_LOGO_URL")
# Политика ПДн — та же страница, что на promostaff.pro (лендинг PRO).
PRIVACY_POLICY_URL = _env("PRIVACY_POLICY_URL") or "https://promostaff.pro/privacy"
ANKETA_URL = _env("ANKETA_URL") or "https://promostaff-agency.ru/#contact"
PORTFOLIO_URL = _env("PORTFOLIO_URL") or "https://promostaff-agency.ru/#reviews"
CONTACT_PHONE = _env("CONTACT_PHONE") or "+7 (929) 556-56-96"
CONTACT_TELEGRAM = _env("CONTACT_TELEGRAM") or "@promostaffagency"
CONTACT_EMAIL = _env("CONTACT_EMAIL") or "Elektro.07@mail.ru"

# === Базовые ставки (как в Telegram-визитке) ===
RATES = {
    "Хелпер": 750,
    "Грузчик": 750,
    "Промоутер": 800,
    "Гардеробщик": 750,
    "Парковщик": 750,
    "Хостес": 850,
}
SUPERVISOR_TM_LEAD = "Супервайзер/тимлидер"
SUPERVISOR_TM_LEAD_RATE = 900

CLIENT_POSITIONS = list(RATES.keys())


def order_hourly_rates() -> dict[str, int]:
    return {**RATES, SUPERVISOR_TM_LEAD: SUPERVISOR_TM_LEAD_RATE}


APPLICANT_POSITIONS = [
    "Хелпер",
    "Грузчик",
    "Промоутер",
    "Хостес",
    "Гардеробщик",
    "Парковщик",
    "Аниматор",
    "Бариста",
    "Бармен",
    "Официант",
    "Кассир",
    "Шеф-повар",
    "Повар",
    "Мойщик посуды",
    "Уборщик",
    "Охранник",
    "Водитель",
    "Шаттл-водитель",
    "Звукорежиссёр",
    "Светорежиссёр",
    "Видеооператор",
    "Монтажник сцены",
    "Разнорабочий",
    "Электрик",
    "Строитель",
    "Фотограф",
    "Видеограф",
    "Диджей",
    "Ведущий",
    "Модель",
    "Стилист",
    "Визажист",
    "Костюмер",
    "Супервайзер",
]

EXPERIENCE_OPTIONS = ["Менее года", "1-3 года", "Более 3 лет"]

# Опционально: ссылки для кнопки «Бот PRO» (если отличается от Telegram-агентства).
AGENCY_SITE_URL = _env("AGENCY_SITE_URL")
AGENCY_EMAIL = _env("AGENCY_EMAIL")
AGENCY_PHONE = _env("AGENCY_PHONE")
PRO_TELEGRAM_BOT_URL = _env("PRO_TELEGRAM_BOT_URL")

# Уведомления администраторам (почта + MAX user id).
SMTP_HOST = _env("SMTP_HOST")
SMTP_PORT = _env_int("SMTP_PORT", 587)
SMTP_USER = _env("SMTP_USER")
SMTP_PASSWORD = _env("SMTP_PASSWORD")
SMTP_FROM = _env("SMTP_FROM")
# Как в Telegram-боте: EMAIL_RECEIVER; в Timeweb можно задать NOTIFY_EMAIL_TO.
NOTIFY_EMAIL_TO = _env("NOTIFY_EMAIL_TO") or _env("EMAIL_RECEIVER")
SMTP_USE_TLS = _env_bool("SMTP_USE_TLS", True)
ADMIN_MAX_USER_IDS = _env_int_list("ADMIN_MAX_USER_IDS")


def contact_phone_tel() -> str:
    """Телефон в формате +7… (без tel: в кнопках мессенджеров)."""
    d = re.sub(r"[^\d+]", "", CONTACT_PHONE)
    if d.startswith("8") and len(d) >= 11:
        d = "+7" + d[1:]
    if d and not d.startswith("+"):
        d = "+" + d
    return d or CONTACT_PHONE


def contact_phone_digits() -> str:
    d = re.sub(r"\D", "", CONTACT_PHONE)
    if len(d) == 11 and d[0] in ("7", "8"):
        return "7" + d[1:]
    if len(d) == 10 and d[0] == "9":
        return "7" + d
    return d


def contact_whatsapp_url() -> str:
    num = contact_phone_digits()
    return f"https://wa.me/{num}" if num else "https://wa.me/"


def contact_telegram_url() -> str:
    h = CONTACT_TELEGRAM.strip().lstrip("@")
    return f"https://t.me/{h}" if h else "https://t.me/"
