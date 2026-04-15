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
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS agency_visit_orders (
                    id BIGSERIAL PRIMARY KEY,
                    source TEXT NOT NULL DEFAULT 'max',
                    user_id BIGINT,
                    username TEXT,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS agency_visit_join_requests (
                    id BIGSERIAL PRIMARY KEY,
                    source TEXT NOT NULL DEFAULT 'max',
                    user_id BIGINT,
                    username TEXT,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS agency_visit_questions (
                    id BIGSERIAL PRIMARY KEY,
                    source TEXT NOT NULL DEFAULT 'max',
                    user_id BIGINT,
                    username TEXT,
                    question TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
                """
            )
    logger.info("agency_max_funnel schema ensured")


def save_visit_order(max_user_id: int, username: str, payload_json: str) -> int | None:
    if not DATABASE_URL:
        return None
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agency_visit_orders (source, user_id, username, payload)
                VALUES ('max', %s, %s, %s::jsonb)
                RETURNING id
                """,
                (max_user_id, username, payload_json),
            )
            row = cur.fetchone()
            return int(row[0]) if row else None


def save_visit_join(max_user_id: int, username: str, payload_json: str) -> int | None:
    if not DATABASE_URL:
        return None
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agency_visit_join_requests (source, user_id, username, payload)
                VALUES ('max', %s, %s, %s::jsonb)
                RETURNING id
                """,
                (max_user_id, username, payload_json),
            )
            row = cur.fetchone()
            return int(row[0]) if row else None


def save_visit_question(max_user_id: int, username: str, question: str) -> int | None:
    if not DATABASE_URL:
        return None
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agency_visit_questions (source, user_id, username, question)
                VALUES ('max', %s, %s, %s)
                RETURNING id
                """,
                (max_user_id, username, question),
            )
            row = cur.fetchone()
            return int(row[0]) if row else None


def get_visitcard_stats() -> dict[str, int]:
    if not DATABASE_URL:
        return {"orders": 0, "join": 0, "questions": 0}
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM agency_visit_orders")
            orders = int((cur.fetchone() or [0])[0] or 0)
            cur.execute("SELECT COUNT(*) FROM agency_visit_join_requests")
            join = int((cur.fetchone() or [0])[0] or 0)
            cur.execute("SELECT COUNT(*) FROM agency_visit_questions")
            questions = int((cur.fetchone() or [0])[0] or 0)
    return {"orders": orders, "join": join, "questions": questions}


def list_visit_rows(kind: str, limit: int = 100, date_from: str = "", date_to: str = "") -> list[dict]:
    if not DATABASE_URL:
        return []
    table_map = {
        "orders": "agency_visit_orders",
        "join": "agency_visit_join_requests",
        "questions": "agency_visit_questions",
    }
    table = table_map.get(kind)
    if not table:
        return []
    where = []
    params: list = []
    if date_from:
        where.append("date(created_at) >= date(%s)")
        params.append(date_from)
    if date_to:
        where.append("date(created_at) <= date(%s)")
        params.append(date_to)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    with connection() as conn:
        with conn.cursor() as cur:
            if kind == "questions":
                cur.execute(
                    f"""
                    SELECT id, created_at, user_id, username, question
                    FROM {table}
                    {where_sql}
                    ORDER BY id DESC
                    LIMIT %s
                    """,
                    (*params, int(limit)),
                )
                rows = cur.fetchall() or []
                return [
                    {"id": int(r[0]), "created_at": str(r[1] or ""), "user_id": int(r[2] or 0), "username": str(r[3] or ""), "question": str(r[4] or "")}
                    for r in rows
                ]
            cur.execute(
                f"""
                SELECT id, created_at, user_id, username, payload::text
                FROM {table}
                {where_sql}
                ORDER BY id DESC
                LIMIT %s
                """,
                (*params, int(limit)),
            )
            rows = cur.fetchall() or []
            return [
                {"id": int(r[0]), "created_at": str(r[1] or ""), "user_id": int(r[2] or 0), "username": str(r[3] or ""), "payload": str(r[4] or "{}")}
                for r in rows
            ]


def list_max_join_broadcast_targets(
    position: str = "",
    experience_years: str = "",
    priority_only: bool = False,
    limit: int = 1500,
) -> list[dict]:
    if not DATABASE_URL:
        return []
    where = ["source = 'max'", "user_id IS NOT NULL"]
    params: list = []
    if position:
        where.append("payload ->> 'position' = %s")
        params.append(position)
    if experience_years:
        where.append("payload ->> 'experience_years' = %s")
        params.append(experience_years)
    if priority_only:
        where.append("COALESCE((payload ->> 'priority_pool')::boolean, false) = true")
    where_sql = " AND ".join(where)
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT user_id, username, payload ->> 'position', payload ->> 'experience_years'
                FROM agency_visit_join_requests
                WHERE {where_sql}
                ORDER BY user_id DESC
                LIMIT %s
                """,
                (*params, int(limit)),
            )
            rows = cur.fetchall() or []
    return [
        {
            "user_id": int(r[0] or 0),
            "username": str(r[1] or ""),
            "position": str(r[2] or ""),
            "experience_years": str(r[3] or ""),
        }
        for r in rows
        if int(r[0] or 0) > 0
    ]
