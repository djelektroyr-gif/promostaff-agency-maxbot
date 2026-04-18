"""Опциональное подключение к Postgres для воронки и напоминаний (схема как в PROMOSTAFF PRO)."""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg2

from config import DATABASE_URL, PD_CONSENT_VERSION

logger = logging.getLogger(__name__)

# Синхронно с promostaff-bot/services/messenger_user_policy.py
_MAX_TG_SYNTHETIC_LEAST = 10**15
PRO_PG_MAX_VISIT_CLIENT = "agency_max_visit_client"


def _synthetic_tg_for_max(max_user_id: int) -> int:
    return _MAX_TG_SYNTHETIC_LEAST + int(max_user_id)


def _client_tg_id_for_max_cp(max_user_id: int) -> int:
    """tg_id для cp_requests.client_tg_id (FK users): сначала строка с max_user_id, иначе синтетика."""
    uid = int(max_user_id)
    if not DATABASE_URL:
        return _synthetic_tg_for_max(uid)
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT tg_id FROM users WHERE max_user_id = %s LIMIT 1",
                    (uid,),
                )
                row = cur.fetchone()
                if row:
                    return int(row[0])
    except Exception:
        logger.exception("_client_tg_id_for_max_cp max_uid=%s", uid)
    return _synthetic_tg_for_max(uid)


def _pg_upsert_user_for_max_visit_client(
    max_user_id: int, username: str, data: dict[str, Any]
) -> None:
    """После регистрации заказчика в MAX — строка в users (нужна для cp_requests и панели)."""
    if not DATABASE_URL:
        return
    uid = int(max_user_id)
    cn = (data.get("contact_name") or "").strip()
    tg_row = _client_tg_id_for_max_cp(uid)
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (
                        tg_id, max_user_id, role, company_name, contact_person, phone, inn, org_position, full_name,
                        pd_consent_at, pd_consent_version, funnel_completed_at, pro_access_at, pro_access_source,
                        updated_at
                    ) VALUES (
                        %s, %s, 'client', %s, %s, %s, %s, %s, %s,
                        NOW(), %s, NOW(), NOW(), %s, NOW()
                    )
                    ON CONFLICT (tg_id) DO UPDATE SET
                        max_user_id = COALESCE(EXCLUDED.max_user_id, users.max_user_id),
                        role = 'client',
                        company_name = EXCLUDED.company_name,
                        contact_person = EXCLUDED.contact_person,
                        phone = EXCLUDED.phone,
                        inn = EXCLUDED.inn,
                        org_position = EXCLUDED.org_position,
                        full_name = EXCLUDED.full_name,
                        pd_consent_at = COALESCE(users.pd_consent_at, EXCLUDED.pd_consent_at),
                        pd_consent_version = COALESCE(users.pd_consent_version, EXCLUDED.pd_consent_version),
                        funnel_completed_at = COALESCE(users.funnel_completed_at, EXCLUDED.funnel_completed_at),
                        pro_access_at = EXCLUDED.pro_access_at,
                        pro_access_source = EXCLUDED.pro_access_source,
                        updated_at = NOW()
                    """,
                    (
                        tg_row,
                        uid,
                        (data.get("company_name") or "").strip(),
                        cn,
                        (data.get("phone") or "").strip(),
                        (data.get("inn") or "").strip(),
                        (data.get("position_in_org") or "").strip(),
                        cn,
                        (PD_CONSENT_VERSION or "").strip() or "agency_visit_v1",
                        PRO_PG_MAX_VISIT_CLIENT,
                    ),
                )
    except Exception:
        logger.exception("_pg_upsert_user_for_max_visit_client max_uid=%s", uid)


def _sync_cp_request_from_max_visit_order(
    max_user_id: int, username: str, payload: dict[str, Any], agency_order_pg_id: int
) -> int | None:
    """Панель «Запрос КП»: cp_requests + agency_crm_cards (как в Telegram-визитке)."""
    if not DATABASE_URL:
        return None
    from datetime import datetime

    client_tg_id = _client_tg_id_for_max_cp(max_user_id)
    y = datetime.now().year
    et = (payload.get("event_type") or "").strip()
    city = (payload.get("city") or "").strip()
    title = f"{et} · {city}" if et and city else (et or city or "Запрос КП (MAX визитка)")
    title = title[:500]
    brief = {
        "source": "agency_visit_card_max",
        "max_user_id": int(max_user_id),
        "agency_visit_order_id": int(agency_order_pg_id),
        "visit_public_ref": payload.get("public_ref"),
        "username": (username or "").strip(),
    }
    comment = json.dumps(brief, ensure_ascii=False)[:8000]
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO cp_requests (public_number, client_tg_id, company_id, channel, status, title, client_comment)
                    VALUES (NULL, %s, NULL, 'max', 'collecting_brief', %s, %s)
                    RETURNING id
                    """,
                    (int(client_tg_id), title, comment),
                )
                row = cur.fetchone()
                if not row:
                    conn.rollback()
                    return None
                rid = int(row[0])
                pub = f"KP-{y}-{rid:06d}"
                cur.execute(
                    "UPDATE cp_requests SET public_number = %s, updated_at = NOW() WHERE id = %s",
                    (pub, rid),
                )
                card_title = title if len(title) > 8 else f"Запрос КП {pub}"
                cur.execute(
                    """
                    INSERT INTO agency_crm_cards (pipeline, stage, source_kind, source_id, client_tg_id, title, created_at, updated_at)
                    VALUES ('kp', 'new', 'cp_request', %s, %s, %s, NOW(), NOW())
                    ON CONFLICT (source_kind, source_id) DO NOTHING
                    """,
                    (rid, int(client_tg_id), card_title[:500]),
                )
        return rid
    except Exception:
        logger.exception(
            "_sync_cp_request_from_max_visit_order max_uid=%s order_id=%s",
            max_user_id,
            agency_order_pg_id,
        )
        return None

_LOCAL_CLIENT_DB = Path(__file__).resolve().parent / "data" / "max_visit_clients.sqlite"


def _ensure_local_client_db() -> None:
    _LOCAL_CLIENT_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_LOCAL_CLIENT_DB)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS max_visit_clients (
                max_user_id INTEGER PRIMARY KEY,
                username TEXT,
                company_name TEXT,
                contact_name TEXT,
                position_in_org TEXT,
                phone TEXT,
                inn TEXT,
                verified_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        cur = conn.execute("PRAGMA table_info(max_visit_clients)")
        lcols = {r[1] for r in cur.fetchall()}
        if "contact_email" not in lcols:
            conn.execute(
                "ALTER TABLE max_visit_clients ADD COLUMN contact_email TEXT NOT NULL DEFAULT ''"
            )
        conn.commit()
    finally:
        conn.close()


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
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS agency_max_visit_clients (
                    max_user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    company_name TEXT,
                    contact_name TEXT,
                    position_in_org TEXT,
                    phone TEXT,
                    inn TEXT,
                    verified_at TIMESTAMP DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name = 'agency_max_visit_clients'
                          AND column_name = 'contact_email'
                    ) THEN
                        ALTER TABLE agency_max_visit_clients
                        ADD COLUMN contact_email TEXT DEFAULT '';
                    END IF;
                END $$;
                """
            )
    logger.info("agency_max_funnel schema ensured")


def get_max_visit_client(max_user_id: int) -> dict[str, Any] | None:
    """Данные проверенного заказчика MAX (для подстановки в форму заказа)."""
    uid = int(max_user_id)
    if DATABASE_URL:
        try:
            with connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT company_name, contact_name, position_in_org, phone, inn, contact_email
                        FROM agency_max_visit_clients
                        WHERE max_user_id = %s
                        """,
                        (uid,),
                    )
                    row = cur.fetchone()
                    if not row:
                        return None
                    return {
                        "company_name": row[0] or "",
                        "contact_name": row[1] or "",
                        "position_in_org": row[2] or "",
                        "phone": row[3] or "",
                        "inn": row[4] or "",
                        "contact_email": row[5] or "",
                    }
        except Exception:
            logger.exception("get_max_visit_client pg")
    try:
        _ensure_local_client_db()
        conn = sqlite3.connect(_LOCAL_CLIENT_DB)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT company_name, contact_name, position_in_org, phone, inn, contact_email
                FROM max_visit_clients
                WHERE max_user_id = ?
                """,
                (uid,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "company_name": row[0] or "",
                "contact_name": row[1] or "",
                "position_in_org": row[2] or "",
                "phone": row[3] or "",
                "inn": row[4] or "",
                "contact_email": (row[5] if len(row) > 5 else "") or "",
            }
        finally:
            conn.close()
    except Exception:
        logger.exception("get_max_visit_client local")
    return None


def is_max_visit_client_verified(max_user_id: int) -> bool:
    """Заказчик прошёл предапроверку (как visit_clients в Telegram-визитке)."""
    uid = int(max_user_id)
    if DATABASE_URL:
        try:
            with connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM agency_max_visit_clients WHERE max_user_id = %s",
                        (uid,),
                    )
                    return bool(cur.fetchone())
        except Exception:
            logger.exception("is_max_visit_client_verified pg")
    try:
        _ensure_local_client_db()
        conn = sqlite3.connect(_LOCAL_CLIENT_DB)
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM max_visit_clients WHERE max_user_id = ?", (uid,))
            return bool(cur.fetchone())
        finally:
            conn.close()
    except Exception:
        logger.exception("is_max_visit_client_verified local")
    return False


def is_max_visit_worker_verified(max_user_id: int) -> bool:
    """Исполнитель верифицирован в MAX (аналог visit_workers в Telegram). Пока нет учёта — False."""
    _ = int(max_user_id)
    return False


def save_max_visit_client_verified(max_user_id: int, username: str, data: dict[str, Any]) -> None:
    uid = int(max_user_id)
    un = (username or "").strip()
    cn = (data.get("company_name") or "").strip()
    contact = (data.get("contact_name") or "").strip()
    pos = (data.get("position_in_org") or "").strip()
    phone = (data.get("phone") or "").strip()
    inn = (data.get("inn") or "").strip()
    cemail = (data.get("contact_email") or "").strip()
    if DATABASE_URL:
        try:
            with connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO agency_max_visit_clients (
                            max_user_id, username, company_name, contact_name, position_in_org, phone, inn, contact_email
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (max_user_id) DO UPDATE SET
                            username = EXCLUDED.username,
                            company_name = EXCLUDED.company_name,
                            contact_name = EXCLUDED.contact_name,
                            position_in_org = EXCLUDED.position_in_org,
                            phone = EXCLUDED.phone,
                            inn = EXCLUDED.inn,
                            contact_email = EXCLUDED.contact_email,
                            verified_at = NOW()
                        """,
                        (uid, un, cn, contact, pos, phone, inn, cemail),
                    )
            _pg_upsert_user_for_max_visit_client(
                uid,
                un,
                {
                    "company_name": cn,
                    "contact_name": contact,
                    "position_in_org": pos,
                    "phone": phone,
                    "inn": inn,
                },
            )
            return
        except Exception:
            logger.exception("save_max_visit_client_verified pg")
    try:
        _ensure_local_client_db()
        conn = sqlite3.connect(_LOCAL_CLIENT_DB)
        try:
            conn.execute(
                """
                INSERT INTO max_visit_clients (
                    max_user_id, username, company_name, contact_name, position_in_org, phone, inn, contact_email
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(max_user_id) DO UPDATE SET
                    username = excluded.username,
                    company_name = excluded.company_name,
                    contact_name = excluded.contact_name,
                    position_in_org = excluded.position_in_org,
                    phone = excluded.phone,
                    inn = excluded.inn,
                    contact_email = excluded.contact_email,
                    verified_at = datetime('now')
                """,
                (uid, un, cn, contact, pos, phone, inn, cemail),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.exception("save_max_visit_client_verified local")


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


def save_visit_order_payload(max_user_id: int, username: str, data: dict[str, Any]) -> tuple[int | None, str]:
    """INSERT в CRM + public_ref PSA-{id} в payload. Возвращает (pg_id, public_ref)."""
    if not DATABASE_URL:
        return None, "OFFLINE"
    import json as _json

    base = dict(data)
    payload_s = _json.dumps(base, ensure_ascii=False)
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agency_visit_orders (source, user_id, username, payload)
                VALUES ('max', %s, %s, %s::jsonb)
                RETURNING id
                """,
                (int(max_user_id), username, payload_s),
            )
            row = cur.fetchone()
            pg_id = int(row[0]) if row else None
    ref = f"PSA-{pg_id}" if pg_id else "—"
    base["public_ref"] = ref
    if pg_id:
        base["crm_id"] = pg_id
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE agency_visit_orders SET payload = %s::jsonb WHERE id = %s",
                    (_json.dumps(base, ensure_ascii=False), pg_id),
                )
        if (base.get("order_kind") or "").strip() == "cp_request":
            cp_rid = _sync_cp_request_from_max_visit_order(
                int(max_user_id), (username or "").strip(), base, int(pg_id)
            )
            if cp_rid:
                base["cp_request_id"] = cp_rid
                with connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE agency_visit_orders SET payload = %s::jsonb WHERE id = %s",
                            (_json.dumps(base, ensure_ascii=False), pg_id),
                        )
    return pg_id, ref


def list_agency_visit_orders_for_user(max_user_id: int, limit: int = 20) -> list[dict[str, Any]]:
    if not DATABASE_URL:
        return []
    lim = max(1, min(int(limit), 50))
    uid = int(max_user_id)
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, payload, created_at
                FROM agency_visit_orders
                WHERE user_id = %s AND source = 'max'
                ORDER BY id DESC
                LIMIT %s
                """,
                (uid, lim),
            )
            rows = cur.fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        p = r[1]
        if not isinstance(p, dict):
            try:
                import json as _json

                p = _json.loads(p) if isinstance(p, str) else {}
            except Exception:
                p = {}
        out.append(
            {
                "crm_id": int(r[0]),
                "created_at": r[2],
                "payload": p,
                "public_ref": (p.get("public_ref") or f"PSA-{int(r[0])}"),
                "order_kind": p.get("order_kind") or "",
            }
        )
    return out


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
