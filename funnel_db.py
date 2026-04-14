"""Опциональное подключение к Postgres для воронки и напоминаний (схема как в PROMOSTAFF PRO)."""
from __future__ import annotations

import logging
from contextlib import contextmanager

import psycopg2

from config import DATABASE_URL

logger = logging.getLogger(__name__)


@contextmanager
def connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_schema() -> None:
    if not DATABASE_URL:
        return
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS agency_max_funnel (
                    max_user_id BIGINT PRIMARY KEY,
                    state TEXT,
                    funnel_last_step TEXT,
                    funnel_last_step_at TIMESTAMP,
                    funnel_phone_reached_at TIMESTAMP,
                    funnel_completed_at TIMESTAMP,
                    funnel_reminder_24h_sent_at TIMESTAMP,
                    funnel_reminder_72h_sent_at TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_agency_max_funnel_incomplete
                ON agency_max_funnel (funnel_last_step_at)
                WHERE funnel_completed_at IS NULL
                """
            )
    logger.info("agency_max_funnel schema ensured")
