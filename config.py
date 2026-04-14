"""Конфиг из окружения (Timeweb / локальный .env). Дефолты — как в PROMOSTAFF-AGENCY BOT (Telegram)."""
from __future__ import annotations

import os
import re


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
FUNNEL_REMINDERS_ENABLED = _env_bool("FUNNEL_REMINDERS_ENABLED", False)
FUNNEL_REMINDERS_INTERVAL_SEC = _env_int("FUNNEL_REMINDERS_INTERVAL_SEC", 600)

# Как в Desktop PROMOSTAFF-AGENCY BOT/config.py (можно переопределить в Timeweb).
COMPANY_NAME = _env("COMPANY_NAME") or "PROMOSTAFF AGENCY"
WEBSITE_URL = _env("WEBSITE_URL") or "https://promostaff-agency.ru"
ANKETA_URL = _env("ANKETA_URL") or "https://promostaff-agency.ru/#contact"
PORTFOLIO_URL = _env("PORTFOLIO_URL") or "https://promostaff-agency.ru/#reviews"
CONTACT_PHONE = _env("CONTACT_PHONE") or "+7 (929) 556-56-96"
CONTACT_TELEGRAM = _env("CONTACT_TELEGRAM") or "@promostaffagency"
CONTACT_EMAIL = _env("CONTACT_EMAIL") or "Elektro.07@mail.ru"

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
    """Телефон для ссылки tel: — только цифры и +."""
    d = re.sub(r"[^\d+]", "", CONTACT_PHONE)
    if d.startswith("8") and len(d) >= 11:
        d = "+7" + d[1:]
    if d and not d.startswith("+"):
        d = "+" + d
    return d or CONTACT_PHONE


def contact_telegram_url() -> str:
    h = CONTACT_TELEGRAM.strip().lstrip("@")
    return f"https://t.me/{h}" if h else "https://t.me/"
