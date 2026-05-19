"""Одноразовая ссылка MAX -> веб-кабинет (/cabinet/enter?token=...)."""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from config import CABINET_WEB_BASE_URL
from funnel_db import connection, resolve_tg_id_for_max_user

logger = logging.getLogger(__name__)

_TOKEN_TTL_MINUTES = 15


def _token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _ensure_table(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS cabinet_web_login_tokens (
            token_hash TEXT PRIMARY KEY,
            tg_id BIGINT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMP NOT NULL,
            used_at TIMESTAMP
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_cabinet_web_login_tokens_tg "
        "ON cabinet_web_login_tokens (tg_id, created_at DESC)"
    )


def build_cabinet_web_login_url(max_user_id: int) -> tuple[str | None, str | None]:
    """Создаёт одноразовую ссылку для MAX-пользователя.

    Возвращает `(url, error_message)`.
    """
    max_uid = int(max_user_id)
    tg_id = resolve_tg_id_for_max_user(max_uid)
    token_raw = secrets.token_urlsafe(32)
    token_digest = _token_hash(token_raw)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=_TOKEN_TTL_MINUTES)

    try:
        with connection() as conn:
            with conn.cursor() as cur:
                _ensure_table(cur)
                cur.execute(
                    "DELETE FROM cabinet_web_login_tokens WHERE tg_id = %s AND used_at IS NULL",
                    (tg_id,),
                )
                cur.execute(
                    """
                    INSERT INTO cabinet_web_login_tokens (token_hash, tg_id, expires_at)
                    VALUES (%s, %s, %s)
                    """,
                    (token_digest, int(tg_id), expires_at),
                )
    except Exception:
        logger.exception("build_cabinet_web_login_url max_uid=%s tg_id=%s", max_uid, tg_id)
        return None, "Не удалось подготовить ссылку. Попробуйте позже."

    url = f"{CABINET_WEB_BASE_URL}/cabinet/enter?token={quote(token_raw, safe='')}"
    return url, None
