"""Конфиг из окружения (Timeweb / локальный .env)."""
import os

MAX_TOKEN = (os.environ.get("MAX_TOKEN") or "").strip()
