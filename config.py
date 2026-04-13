"""Конфиг из окружения (Timeweb / локальный .env)."""
import os


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


MAX_TOKEN = _env("MAX_TOKEN")

# Опционально: ссылки и контакты для визитки (кнопки и тексты).
AGENCY_SITE_URL = _env("AGENCY_SITE_URL")
AGENCY_EMAIL = _env("AGENCY_EMAIL")
AGENCY_PHONE = _env("AGENCY_PHONE")
PRO_TELEGRAM_BOT_URL = _env("PRO_TELEGRAM_BOT_URL")
