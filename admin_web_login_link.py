"""Готовая защищённая ссылка в web-admin MAX (/admin/ui)."""
from __future__ import annotations

from urllib.parse import quote

from config import ADMIN_UI_TOKEN, MAX_ADMIN_UI_BASE_URL


def build_admin_ui_login_url() -> tuple[str | None, str | None]:
    base = (MAX_ADMIN_UI_BASE_URL or "").strip().rstrip("/")
    token = (ADMIN_UI_TOKEN or "").strip()
    if not base:
        return None, "Web admin временно недоступен: не задан MAX_ADMIN_UI_BASE_URL."
    if not (base.startswith("http://") or base.startswith("https://")):
        return None, "Web admin временно недоступен: URL настроен некорректно."
    if not token:
        return None, "Web admin временно недоступен: не задан ADMIN_UI_TOKEN."
    return f"{base}/admin/ui?token={quote(token, safe='')}", None
