"""Журнал попыток входа по телефону (визитка MAX → общая БД)."""
from __future__ import annotations

import logging

from funnel_db import DATABASE_URL, connection

logger = logging.getLogger(__name__)

OUTCOME_LABELS_RU: dict[str, str] = {
    "not_found": "не найден",
    "resume_client_verified": "заказчик ✓",
    "resume_client_pending": "заказчик на проверке",
    "resume_worker_verified": "исполнитель ✓",
    "resume_worker_pending": "исполнитель на проверке",
    "resume_worker_clarification": "исполнитель уточнения",
    "role_conflict": "конфликт роли",
    "ambiguous": "дубликаты в БД",
    "max_conflict": "номер занят другим MAX",
    "continue": "продолжение регистрации",
}


def _ensure_table(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS visit_phone_login_log (
            id BIGSERIAL PRIMARY KEY,
            source TEXT NOT NULL,
            platform_user_id BIGINT NOT NULL,
            username TEXT,
            intended_role TEXT NOT NULL,
            phone TEXT NOT NULL,
            outcome TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_visit_phone_login_log_created
        ON visit_phone_login_log (created_at DESC)
        """
    )


def log_visit_phone_login(
    *,
    source: str,
    platform_user_id: int,
    phone: str,
    intended_role: str,
    outcome: str,
    username: str | None = None,
) -> None:
    if not DATABASE_URL:
        return
    src = (source or "max").strip()[:16]
    role = (intended_role or "client").strip()[:16]
    oc = (outcome or "unknown").strip()[:64]
    ph = (phone or "").strip()[:32]
    un = (username or "").strip()[:64] or None
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                _ensure_table(cur)
                cur.execute(
                    """
                    INSERT INTO visit_phone_login_log (
                        source, platform_user_id, username, intended_role, phone, outcome
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (src, int(platform_user_id), un, role, ph, oc),
                )
    except Exception:
        logger.warning(
            "log_visit_phone_login failed src=%s uid=%s outcome=%s",
            src,
            platform_user_id,
            oc,
            exc_info=True,
        )


def list_visit_phone_login_log(limit: int = 40) -> list[tuple]:
    if not DATABASE_URL:
        return []
    lim = max(1, min(int(limit), 200))
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                _ensure_table(cur)
                cur.execute(
                    """
                    SELECT source, platform_user_id, username, intended_role, phone, outcome, created_at
                    FROM visit_phone_login_log
                    ORDER BY id DESC
                    LIMIT %s
                    """,
                    (lim,),
                )
                return list(cur.fetchall() or [])
    except Exception:
        logger.exception("list_visit_phone_login_log")
        return []
