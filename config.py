"""Конфиг из окружения (Timeweb / локальный .env)."""
import os


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

# Опционально: ссылки и контакты для визитки (кнопки и тексты).
AGENCY_SITE_URL = _env("AGENCY_SITE_URL")
AGENCY_EMAIL = _env("AGENCY_EMAIL")
AGENCY_PHONE = _env("AGENCY_PHONE")
PRO_TELEGRAM_BOT_URL = _env("PRO_TELEGRAM_BOT_URL")

# Уведомления администраторам по почте (если заданы host/from/to и пароль при необходимости).
SMTP_HOST = _env("SMTP_HOST")
SMTP_PORT = _env_int("SMTP_PORT", 587)
SMTP_USER = _env("SMTP_USER")
SMTP_PASSWORD = _env("SMTP_PASSWORD")
SMTP_FROM = _env("SMTP_FROM")
# Одна или несколько почт через запятую.
NOTIFY_EMAIL_TO = _env("NOTIFY_EMAIL_TO")
SMTP_USE_TLS = _env_bool("SMTP_USE_TLS", True)

# Уведомления в MAX: user_id контактов (числа через запятую), куда бот шлёт служебные тексты.
ADMIN_MAX_USER_IDS = _env_int_list("ADMIN_MAX_USER_IDS")
