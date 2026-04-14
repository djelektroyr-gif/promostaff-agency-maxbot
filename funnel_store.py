"""
Синхронизация FSM (visit_flows.SESSIONS) с Postgres — те же смыслы полей, что funnel_* у users в PRO.

Ключ: max_user_id. Без DATABASE_URL функции no-op.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from config import DATABASE_URL

logger = logging.getLogger(__name__)


def _utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _state_from_session(s: dict[str, Any]) -> str | None:
    flow = (s.get("flow") or "").strip()
    step = (s.get("step") or "").strip()
    if not flow or not step:
        return None
    return f"reg_{flow}_{step}"


def _session_has_phone(s: dict[str, Any]) -> bool:
    data = s.get("data") if isinstance(s.get("data"), dict) else {}
    phone = (data.get("phone") or "").strip()
    if phone:
        return True
    cph = (data.get("contact_phone") or "").strip()
    return bool(cph)


def funnel_sync_session(max_user_id: int, session: dict[str, Any] | None) -> None:
    """Актуальный шаг воронки в БД; session=None — сброс незавершённой воронки (меню / старт)."""
    if not DATABASE_URL:
        return
    try:
        from funnel_db import connection
    except Exception:
        return

    if session is None:
        try:
            with connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE agency_max_funnel SET
                            state = NULL,
                            funnel_last_step = NULL,
                            funnel_reminder_24h_sent_at = NULL,
                            funnel_reminder_72h_sent_at = NULL,
                            updated_at = NOW()
                        WHERE max_user_id = %s AND funnel_completed_at IS NULL
                        """,
                        (max_user_id,),
                    )
        except Exception as e:
            logger.warning("funnel abandon skip max_user_id=%s: %s", max_user_id, e)
        return

    st = _state_from_session(session)
    if not st:
        return
    has_phone = _session_has_phone(session)
    now = _utc_naive()
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agency_max_funnel (
                        max_user_id, state, funnel_last_step, funnel_last_step_at, updated_at
                    ) VALUES (%s, %s, %s, %s, NOW())
                    ON CONFLICT (max_user_id) DO UPDATE SET
                        state = EXCLUDED.state,
                        funnel_last_step = EXCLUDED.funnel_last_step,
                        funnel_last_step_at = EXCLUDED.funnel_last_step_at,
                        updated_at = NOW()
                    WHERE agency_max_funnel.funnel_completed_at IS NULL
                    """,
                    (max_user_id, st, st, now),
                )
                if has_phone:
                    cur.execute(
                        """
                        UPDATE agency_max_funnel SET
                            funnel_phone_reached_at = COALESCE(funnel_phone_reached_at, %s),
                            updated_at = NOW()
                        WHERE max_user_id = %s AND funnel_completed_at IS NULL
                        """,
                        (now, max_user_id),
                    )
    except Exception as e:
        logger.warning("funnel sync skip max_user_id=%s: %s", max_user_id, e)


def funnel_touch_complete(max_user_id: int) -> None:
    if not DATABASE_URL:
        return
    try:
        from funnel_db import connection
    except Exception:
        return
    now = _utc_naive()
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agency_max_funnel (
                        max_user_id, state, funnel_last_step, funnel_last_step_at,
                        funnel_completed_at, updated_at
                    ) VALUES (%s, NULL, 'completed', %s, %s, NOW())
                    ON CONFLICT (max_user_id) DO UPDATE SET
                        state = NULL,
                        funnel_last_step = 'completed',
                        funnel_last_step_at = EXCLUDED.funnel_last_step_at,
                        funnel_completed_at = EXCLUDED.funnel_completed_at,
                        updated_at = NOW()
                    """,
                    (max_user_id, now, now),
                )
    except Exception as e:
        logger.warning("funnel complete skip max_user_id=%s: %s", max_user_id, e)
