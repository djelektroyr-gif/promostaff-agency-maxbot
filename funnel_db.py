"""Опциональное подключение к Postgres для воронки и напоминаний (схема как в PROMOSTAFF PRO)."""
from __future__ import annotations

import json
import logging
import re
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


def worker_tg_id_for_max(max_user_id: int) -> int:
    """Синтетический tg_id для нового MAX-only пользователя."""
    return _MAX_TG_SYNTHETIC_LEAST + int(max_user_id)


def _synthetic_tg_for_max(max_user_id: int) -> int:
    return worker_tg_id_for_max(max_user_id)


def resolve_tg_id_for_max_user(max_user_id: int) -> int:
    """Канонический users.tg_id: строка с max_user_id, иначе синтетика."""
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
        logger.exception("resolve_tg_id_for_max_user max_uid=%s", uid)
    return _synthetic_tg_for_max(uid)


def _worker_lookup_ids_for_max(max_user_id: int) -> tuple[int, ...]:
    """Кандидаты user_id для MAX-исполнителя: canonical tg_id и synthetic fallback."""
    uid = int(max_user_id)
    canonical = resolve_tg_id_for_max_user(uid)
    synthetic = worker_tg_id_for_max(uid)
    if canonical == synthetic:
        return (canonical,)
    return (canonical, synthetic)


WORKER_STATUS_PENDING_REVIEW = "pending_review"
WORKER_STATUS_CLARIFICATION = "clarification_needed"
WORKER_STATUS_REJECTED = "rejected"
WORKER_STATUS_APPROVED = "approved"
COOPERATION_MODE_AGENCY = "agency"
COOPERATION_MODE_PLATFORM = "platform"
COOPERATION_MODE_CUSTOMER = "customer"
VALID_COOPERATION_MODES = frozenset(
    {COOPERATION_MODE_AGENCY, COOPERATION_MODE_PLATFORM, COOPERATION_MODE_CUSTOMER}
)
COMPANY_MEMBER_VER_APPROVED = "approved"
COMPANY_MEMBER_VER_PENDING = "pending"
_HRM_PIPELINE = "hrm"
_HRM_JOIN_SOURCE = "agency_visit_join"
_SHIFT_ACTION_SOURCE_COLS_READY = False


def normalize_cooperation_mode(raw: object) -> str:
    mode = str(raw or "").strip().lower()
    if mode in VALID_COOPERATION_MODES:
        return mode
    return COOPERATION_MODE_AGENCY


def _ensure_shift_action_source_columns_max() -> None:
    global _SHIFT_ACTION_SOURCE_COLS_READY
    if _SHIFT_ACTION_SOURCE_COLS_READY or not DATABASE_URL:
        return
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "ALTER TABLE shift_assignments ADD COLUMN IF NOT EXISTS last_action_source TEXT"
                )
                cur.execute(
                    "ALTER TABLE shift_assignments ADD COLUMN IF NOT EXISTS last_action_at TIMESTAMP"
                )
        _SHIFT_ACTION_SOURCE_COLS_READY = True
    except Exception:
        logger.debug("ensure shift action source columns skipped", exc_info=True)


def _client_tg_id_for_max_cp(
    max_user_id: int,
    *,
    phone: str | None = None,
    data: dict[str, Any] | None = None,
) -> int:
    """tg_id для FK users: canonical из сессии/телефона, иначе max_user_id, иначе синтетика."""
    uid = int(max_user_id)
    if data:
        ctg = data.get("canonical_user_tg_id")
        if ctg is not None:
            return int(ctg)
    if phone:
        try:
            from user_identity import find_users_by_phone

            rows = find_users_by_phone(phone)
            if len(rows) == 1:
                return int(rows[0]["tg_id"])
        except Exception:
            logger.exception("_client_tg_id_for_max_cp phone max_uid=%s", uid)
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


def _pg_undefined_column(exc: BaseException) -> bool:
    err = (str(exc) or "").lower()
    return "undefinedcolumn" in err or "does not exist" in err


def _ensure_visit_clients_contact_email_column(cur) -> None:
    try:
        cur.execute("ALTER TABLE visit_clients ADD COLUMN IF NOT EXISTS contact_email TEXT")
    except Exception:
        logger.warning("visit_clients.contact_email ensure failed", exc_info=True)


def _upsert_visit_clients_profile_pg(
    cur,
    tg_row: int,
    company_name: str,
    contact_name: str,
    phone: str,
    contact_email: str,
) -> None:
    _ensure_visit_clients_contact_email_column(cur)
    cur.execute("SAVEPOINT sp_visit_clients_profile")
    try:
        cur.execute(
            """
            INSERT INTO visit_clients (
                user_id, company_name, contact_name, phone, contact_email, verified_at, created_at
            ) VALUES (%s, %s, %s, %s, %s, NULL, NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                company_name = EXCLUDED.company_name,
                contact_name = EXCLUDED.contact_name,
                phone = EXCLUDED.phone,
                contact_email = COALESCE(NULLIF(EXCLUDED.contact_email, ''), visit_clients.contact_email)
            """,
            (tg_row, company_name, contact_name, phone, contact_email),
        )
        cur.execute("RELEASE SAVEPOINT sp_visit_clients_profile")
    except Exception as exc:
        if not _pg_undefined_column(exc):
            cur.execute("ROLLBACK TO SAVEPOINT sp_visit_clients_profile")
            raise
        cur.execute("ROLLBACK TO SAVEPOINT sp_visit_clients_profile")
        logger.warning(
            "visit_clients profile without contact_email tg_id=%s",
            tg_row,
        )
        cur.execute(
            """
            INSERT INTO visit_clients (
                user_id, company_name, contact_name, phone, verified_at, created_at
            ) VALUES (%s, %s, %s, %s, NULL, NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                company_name = EXCLUDED.company_name,
                contact_name = EXCLUDED.contact_name,
                phone = EXCLUDED.phone
            """,
            (tg_row, company_name, contact_name, phone),
        )


def _upsert_users_row_for_max_visit_client(
    cur,
    *,
    tg_row: int,
    max_user_id: int,
    data: dict[str, Any],
    company_id: int | None,
) -> None:
    """Строка users до visit_clients/clients — как save_client() в agency-bot."""
    uid = int(max_user_id)
    cn = (data.get("contact_name") or "").strip()
    company_name = (data.get("company_name") or "").strip()
    phone = (data.get("phone") or "").strip()
    inn = (data.get("inn") or "").strip()
    pos = (data.get("position_in_org") or "").strip()
    pd_ver = (PD_CONSENT_VERSION or "").strip() or "agency_visit_v1"
    params_full = (
        int(tg_row),
        uid,
        company_id,
        company_name,
        cn,
        phone,
        inn,
        pos,
        cn,
        pd_ver,
        PRO_PG_MAX_VISIT_CLIENT,
    )
    try:
        cur.execute(
            """
            INSERT INTO users (
                tg_id, max_user_id, role, company_id, company_name, contact_person, phone, inn, org_position, full_name,
                pd_consent_at, pd_consent_version, funnel_completed_at, pro_access_at, pro_access_source,
                created_at, updated_at
            ) VALUES (
                %s, %s, 'client', %s, %s, %s, %s, %s, %s, %s,
                NOW(), %s, NOW(), NOW(), %s, NOW(), NOW()
            )
            ON CONFLICT (tg_id) DO UPDATE SET
                max_user_id = COALESCE(EXCLUDED.max_user_id, users.max_user_id),
                role = 'client',
                company_id = COALESCE(EXCLUDED.company_id, users.company_id),
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
            params_full,
        )
        return
    except Exception as exc:
        if not _pg_undefined_column(exc):
            raise
        logger.warning(
            "upsert users max client: extended columns missing, fallback tg_id=%s max_uid=%s",
            tg_row,
            uid,
        )
    cur.execute(
        """
        INSERT INTO users (
            tg_id, role, full_name, phone, company_id, company_name, contact_person, created_at, updated_at
        ) VALUES (%s, 'client', %s, %s, %s, %s, %s, NOW(), NOW())
        ON CONFLICT (tg_id) DO UPDATE SET
            role = 'client',
            full_name = EXCLUDED.full_name,
            phone = EXCLUDED.phone,
            company_id = COALESCE(EXCLUDED.company_id, users.company_id),
            company_name = EXCLUDED.company_name,
            contact_person = EXCLUDED.contact_person,
            updated_at = NOW()
        """,
        (int(tg_row), cn, phone, company_id, company_name, cn),
    )
    try:
        cur.execute(
            "UPDATE users SET max_user_id = %s WHERE tg_id = %s AND max_user_id IS NULL",
            (uid, int(tg_row)),
        )
    except Exception as exc2:
        if not _pg_undefined_column(exc2):
            raise


def _pg_upsert_user_for_max_visit_client(
    max_user_id: int, username: str, data: dict[str, Any], company_id: int | None = None
) -> None:
    """После регистрации заказчика в MAX — строка в users (нужна для cp_requests и панели)."""
    if not DATABASE_URL:
        return
    uid = int(max_user_id)
    tg_row = _client_tg_id_for_max_cp(uid, phone=(data.get("phone") or "").strip() or None, data=data)
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                _upsert_users_row_for_max_visit_client(
                    cur,
                    tg_row=tg_row,
                    max_user_id=uid,
                    data=data,
                    company_id=company_id,
                )
    except Exception:
        logger.exception("_pg_upsert_user_for_max_visit_client max_uid=%s", uid)


def _ensure_company_for_max_client(cur, company_name: str, company_inn: str) -> int | None:
    """Создаёт/находит company_id для MAX-регистрации заказчика."""
    name = (company_name or "").strip()
    if not name:
        return None
    inn = (company_inn or "").strip()
    cur.execute("SELECT id FROM companies WHERE name = %s LIMIT 1", (name,))
    row = cur.fetchone()
    if row:
        cid = int(row[0])
        if inn:
            cur.execute("UPDATE companies SET inn = %s WHERE id = %s", (inn, cid))
        return cid
    cur.execute(
        "INSERT INTO companies (name, inn) VALUES (%s, %s) RETURNING id",
        (name, inn or "0000000000"),
    )
    created = cur.fetchone()
    return int(created[0]) if created and created[0] else None


def _sync_cp_request_from_max_visit_order(
    max_user_id: int, username: str, payload: dict[str, Any], agency_order_pg_id: int
) -> int | None:
    """Панель «Запрос КП»: cp_requests + agency_crm_cards (как в Telegram-визитке)."""
    if not DATABASE_URL:
        return None
    from datetime import datetime

    client_tg_id = _client_tg_id_for_max_cp(
        max_user_id,
        phone=(payload.get("contact_phone") or payload.get("phone") or "").strip() or None,
        data=payload if isinstance(payload, dict) else None,
    )
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
                    ON CONFLICT (source_kind, source_id) DO UPDATE SET
                        pipeline = EXCLUDED.pipeline,
                        stage = EXCLUDED.stage,
                        client_tg_id = COALESCE(EXCLUDED.client_tg_id, agency_crm_cards.client_tg_id),
                        title = EXCLUDED.title,
                        updated_at = NOW()
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

def _sync_urgent_crm_card_from_max_visit_order(
    max_user_id: int,
    payload: dict[str, Any],
    agency_order_pg_id: int,
) -> None:
    if not DATABASE_URL:
        return
    order_kind = (payload.get("order_kind") or "").strip().lower()
    if order_kind == "cp_request":
        return
    client_tg_id = _client_tg_id_for_max_cp(
        max_user_id,
        phone=(payload.get("contact_phone") or payload.get("phone") or "").strip() or None,
        data=payload if isinstance(payload, dict) else None,
    )
    et = (payload.get("event_type") or "").strip()
    city = (payload.get("city") or "").strip()
    title = f"{et} · {city}" if et and city else (et or city or "Срочный расчёт")
    title = title[:500]
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agency_crm_cards (
                        pipeline, stage, source_kind, source_id, client_tg_id, title, created_at, updated_at
                    )
                    VALUES ('urgent', 'new', 'agency_visit_order', %s, %s, %s, NOW(), NOW())
                    ON CONFLICT (source_kind, source_id) DO UPDATE SET
                        pipeline = EXCLUDED.pipeline,
                        stage = EXCLUDED.stage,
                        client_tg_id = COALESCE(EXCLUDED.client_tg_id, agency_crm_cards.client_tg_id),
                        title = COALESCE(NULLIF(EXCLUDED.title, ''), agency_crm_cards.title),
                        updated_at = NOW()
                    """,
                    (int(agency_order_pg_id), int(client_tg_id), title),
                )
    except Exception:
        logger.warning(
            "_sync_urgent_crm_card_from_max_visit_order failed max_uid=%s order_id=%s",
            max_user_id,
            agency_order_pg_id,
            exc_info=True,
        )


def _sync_kp_crm_card_for_visit_order(
    max_user_id: int,
    payload: dict[str, Any],
    agency_order_pg_id: int,
) -> None:
    if not DATABASE_URL:
        return
    if (payload.get("order_kind") or "").strip().lower() != "cp_request":
        return
    client_tg_id = _client_tg_id_for_max_cp(
        max_user_id,
        phone=(payload.get("contact_phone") or payload.get("phone") or "").strip() or None,
        data=payload if isinstance(payload, dict) else None,
    )
    et = (payload.get("event_type") or "").strip()
    title = (et or f"Запрос КП #{int(agency_order_pg_id)}")[:500]
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agency_crm_cards (
                        pipeline, stage, source_kind, source_id, client_tg_id, title, created_at, updated_at
                    )
                    VALUES ('kp', 'new', 'agency_visit_order', %s, %s, %s, NOW(), NOW())
                    ON CONFLICT (source_kind, source_id) DO UPDATE SET
                        pipeline = EXCLUDED.pipeline,
                        stage = EXCLUDED.stage,
                        client_tg_id = COALESCE(EXCLUDED.client_tg_id, agency_crm_cards.client_tg_id),
                        title = COALESCE(NULLIF(EXCLUDED.title, ''), agency_crm_cards.title),
                        updated_at = NOW()
                    """,
                    (int(agency_order_pg_id), int(client_tg_id), title),
                )
    except Exception:
        logger.warning(
            "_sync_kp_crm_card_for_visit_order failed max_uid=%s order_id=%s",
            max_user_id,
            agency_order_pg_id,
            exc_info=True,
        )


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
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name = 'agency_visit_orders'
                          AND column_name = 'status'
                    ) THEN
                        ALTER TABLE agency_visit_orders
                        ADD COLUMN status TEXT NOT NULL DEFAULT 'new';
                    END IF;
                END $$;
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
            cur.execute(
                """
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name = 'agency_max_visit_clients'
                          AND column_name = 'company_id'
                    ) THEN
                        ALTER TABLE agency_max_visit_clients
                        ADD COLUMN company_id BIGINT;
                    END IF;
                END $$;
                """
            )
            cur.execute(
                "ALTER TABLE visit_clients ADD COLUMN IF NOT EXISTS contact_email TEXT"
            )
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
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS company_subscriptions (
                    company_id BIGINT PRIMARY KEY REFERENCES companies(id) ON DELETE CASCADE,
                    plan_code TEXT NOT NULL DEFAULT 'legacy',
                    status TEXT NOT NULL DEFAULT 'active',
                    projects_limit INTEGER,
                    starts_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    ends_at TIMESTAMP,
                    auto_renew BOOLEAN NOT NULL DEFAULT FALSE,
                    notes TEXT,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_company_subscriptions_status_end
                ON company_subscriptions (status, ends_at)
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS worker_beacon (
                    worker_tg_id BIGINT PRIMARY KEY,
                    is_active INTEGER NOT NULL DEFAULT 0,
                    enabled_at TIMESTAMP,
                    expires_at TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_worker_beacon_expires
                ON worker_beacon (expires_at)
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS assignment_breaks (
                    id BIGSERIAL PRIMARY KEY,
                    shift_id BIGINT NOT NULL,
                    worker_tg_id BIGINT NOT NULL,
                    break_type TEXT NOT NULL,
                    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    ended_at TIMESTAMP,
                    max_minutes INTEGER NOT NULL DEFAULT 10,
                    notes TEXT,
                    auto_closed BOOLEAN NOT NULL DEFAULT FALSE
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_assignment_breaks_open
                ON assignment_breaks (shift_id, worker_tg_id, ended_at)
                """
            )
            cur.execute(
                """
                DO $$ BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = 'workers'
                    ) THEN
                        ALTER TABLE workers
                        ADD COLUMN IF NOT EXISTS cooperation_mode TEXT NOT NULL DEFAULT 'agency';
                        UPDATE workers
                        SET cooperation_mode = 'agency'
                        WHERE COALESCE(BTRIM(cooperation_mode), '') = '';
                    END IF;
                END $$;
                """
            )
            cur.execute(
                """
                UPDATE agency_visit_join_requests
                SET payload = jsonb_set(
                    COALESCE(payload, '{}'::jsonb),
                    '{cooperation_mode}',
                    to_jsonb('agency'::text),
                    true
                )
                WHERE COALESCE(payload->>'cooperation_mode', '') = ''
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


def is_max_visit_client_registered(max_user_id: int) -> bool:
    """Заказчик зарегистрирован (как get_client в Telegram), без учёта verified_at."""
    uid = int(max_user_id)
    tg = resolve_tg_id_for_max_user(uid)
    if DATABASE_URL:
        try:
            with connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT 1 FROM visit_clients WHERE user_id = %s
                        UNION ALL
                        SELECT 1 FROM clients WHERE user_id = %s
                        UNION ALL
                        SELECT 1 FROM agency_max_visit_clients WHERE max_user_id = %s
                        LIMIT 1
                        """,
                        (tg, tg, uid),
                    )
                    return bool(cur.fetchone())
        except Exception:
            logger.exception("is_max_visit_client_registered pg")
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
        logger.exception("is_max_visit_client_registered local")
    return False


def resolve_max_user_id_from_tg_id(tg_id: int) -> int | None:
    """MAX user_id для уведомления заказчика после cvf (users.max_user_id или synthetic tg_id)."""
    tid = int(tg_id)
    if DATABASE_URL:
        try:
            with connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT max_user_id FROM users WHERE tg_id = %s LIMIT 1",
                        (tid,),
                    )
                    row = cur.fetchone()
                    if row and row[0] is not None:
                        return int(row[0])
        except Exception:
            logger.exception("resolve_max_user_id_from_tg_id pg tg_id=%s", tid)
    if tid >= _MAX_TG_SYNTHETIC_LEAST:
        return tid - _MAX_TG_SYNTHETIC_LEAST
    return None


def approve_visit_client_by_tg_id(user_id: int) -> dict:
    """Как promostaff-agency-bot/db.py::approve_visit_client_by_tg_id."""
    uid = int(user_id)
    if not DATABASE_URL:
        return {"user_id": uid, "verified": False, "offline": True}
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO visit_clients (user_id, company_name, contact_name, phone, verified_at, created_at)
                VALUES (%s, '', '', '', NOW(), NOW())
                ON CONFLICT (user_id) DO UPDATE SET
                    verified_at = NOW()
                """,
                (uid,),
            )
            cur.execute(
                "UPDATE users SET role = 'client', updated_at = NOW() WHERE tg_id = %s",
                (uid,),
            )
    return {"user_id": uid, "verified": True}


def reject_pending_client_registration(user_id: int) -> dict | None:
    """Отказ до верификации — как db.py::reject_pending_client_registration."""
    uid = int(user_id)
    if is_max_visit_client_verified_by_tg(uid):
        return None
    if not DATABASE_URL:
        return {"ok": False, "offline": True, "tg_id": uid}
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM clients WHERE user_id = %s", (uid,))
            clients_deleted = int(cur.rowcount or 0)
            cur.execute("DELETE FROM visit_clients WHERE user_id = %s", (uid,))
            visit_deleted = int(cur.rowcount or 0)
            cur.execute(
                """
                UPDATE users
                SET role = 'guest',
                    profession = NULL,
                    updated_at = NOW()
                WHERE tg_id = %s
                  AND LOWER(COALESCE(role, '')) NOT IN ('admin', 'manager', 'администратор', 'менеджер')
                  AND LOWER(COALESCE(role, '')) IN ('client', 'заказчик', 'guest', '')
                """,
                (uid,),
            )
            users_updated = int(cur.rowcount or 0)
            max_uid = resolve_max_user_id_from_tg_id(uid)
            if max_uid is not None:
                cur.execute(
                    "DELETE FROM agency_max_visit_clients WHERE max_user_id = %s",
                    (int(max_uid),),
                )
    return {
        "ok": True,
        "tg_id": uid,
        "clients_deleted": clients_deleted,
        "visit_clients_deleted": visit_deleted,
        "users_updated": users_updated,
    }


def is_max_visit_client_verified_by_tg(tg_id: int) -> bool:
    """verified_at в visit_clients по каноническому tg_id."""
    uid = int(tg_id)
    if not DATABASE_URL:
        return False
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM visit_clients
                    WHERE user_id = %s AND verified_at IS NOT NULL
                    LIMIT 1
                    """,
                    (uid,),
                )
                return bool(cur.fetchone())
    except Exception:
        logger.exception("is_max_visit_client_verified_by_tg tg_id=%s", uid)
    return False


def is_max_visit_client_verified(max_user_id: int) -> bool:
    """Заказчик подтверждён админом (visit_clients.verified_at), как в Telegram."""
    uid = int(max_user_id)
    tg = resolve_tg_id_for_max_user(uid)
    if DATABASE_URL:
        try:
            with connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT 1 FROM visit_clients
                        WHERE user_id = %s AND verified_at IS NOT NULL
                        LIMIT 1
                        """,
                        (tg,),
                    )
                    return bool(cur.fetchone())
        except Exception:
            logger.exception("is_max_visit_client_verified pg")
    try:
        _ensure_local_client_db()
        conn = sqlite3.connect(_LOCAL_CLIENT_DB)
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM max_visit_clients WHERE max_user_id = ? AND verified_at IS NOT NULL",
                (uid,),
            )
            return bool(cur.fetchone())
        finally:
            conn.close()
    except Exception:
        logger.exception("is_max_visit_client_verified local")
    return False


def user_has_prior_bot_pd_context_max(max_user_id: int) -> bool:
    """
    MAX-эквивалент user_has_prior_bot_pd_context:
    если пользователь уже взаимодействовал с контуром (регистрация/заявки/вопросы),
    повторный consent-экран можно не показывать.
    """
    uid = int(max_user_id)
    if uid <= 0:
        return False
    if is_max_visit_client_registered(uid):
        return True
    if has_max_active_executor_profile(uid):
        return True
    if not DATABASE_URL:
        return False
    tg_id = resolve_tg_id_for_max_user(uid)
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM agency_visit_orders
                    WHERE (source = 'max' AND user_id = %s) OR user_id = %s
                    LIMIT 1
                    """,
                    (uid, tg_id),
                )
                if cur.fetchone():
                    return True
                cur.execute(
                    """
                    SELECT 1
                    FROM agency_visit_join_requests
                    WHERE (source = 'max' AND user_id = %s) OR user_id = %s
                    LIMIT 1
                    """,
                    (uid, tg_id),
                )
                if cur.fetchone():
                    return True
                cur.execute(
                    """
                    SELECT 1
                    FROM agency_visit_questions
                    WHERE (source = 'max' AND user_id = %s) OR user_id = %s
                    LIMIT 1
                    """,
                    (uid, tg_id),
                )
                return bool(cur.fetchone())
    except Exception:
        logger.exception("user_has_prior_bot_pd_context_max max_uid=%s", uid)
    return False


def is_max_visit_worker_verified(max_user_id: int) -> bool:
    """Исполнитель одобрен в панели (workers.status = approved), как is_visit_worker_verified."""
    ids = _worker_lookup_ids_for_max(int(max_user_id))
    if DATABASE_URL:
        try:
            with connection() as conn:
                with conn.cursor() as cur:
                    if len(ids) == 1:
                        cur.execute(
                            """
                            SELECT 1 FROM workers
                            WHERE user_id = %s
                              AND COALESCE(status, 'new') = %s
                              AND COALESCE(cooperation_mode, 'agency') = %s
                            LIMIT 1
                            """,
                            (ids[0], WORKER_STATUS_APPROVED, COOPERATION_MODE_AGENCY),
                        )
                    else:
                        cur.execute(
                            """
                            SELECT 1 FROM workers
                            WHERE user_id IN (%s, %s)
                              AND COALESCE(status, 'new') = %s
                              AND COALESCE(cooperation_mode, 'agency') = %s
                            LIMIT 1
                            """,
                            (ids[0], ids[1], WORKER_STATUS_APPROVED, COOPERATION_MODE_AGENCY),
                        )
                    return bool(cur.fetchone())
        except Exception:
            logger.exception("is_max_visit_worker_verified pg")
    return False


def get_max_worker_cooperation_mode(max_user_id: int) -> str:
    ids = _worker_lookup_ids_for_max(int(max_user_id))
    preferred = ids[0]
    if not DATABASE_URL:
        return COOPERATION_MODE_AGENCY
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                if len(ids) == 1:
                    cur.execute(
                        "SELECT COALESCE(cooperation_mode, %s) FROM workers WHERE user_id = %s LIMIT 1",
                        (COOPERATION_MODE_AGENCY, ids[0]),
                    )
                else:
                    cur.execute(
                        """
                        SELECT COALESCE(cooperation_mode, %s)
                        FROM workers
                        WHERE user_id IN (%s, %s)
                        ORDER BY CASE WHEN user_id = %s THEN 0 ELSE 1 END
                        LIMIT 1
                        """,
                        (COOPERATION_MODE_AGENCY, ids[0], ids[1], preferred),
                    )
                row = cur.fetchone()
                if row and row[0]:
                    return normalize_cooperation_mode(row[0])
    except Exception:
        logger.exception("get_max_worker_cooperation_mode max_uid=%s", max_user_id)
    return COOPERATION_MODE_AGENCY


def max_worker_agency_operations_eligible(max_user_id: int) -> bool:
    return bool(is_max_visit_worker_verified(max_user_id))


def has_max_active_executor_profile(max_user_id: int) -> bool:
    """Профиль исполнителя в работе (не rejected), как has_active_executor_profile."""
    ids = _worker_lookup_ids_for_max(int(max_user_id))
    if not DATABASE_URL:
        return False
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                if len(ids) == 1:
                    cur.execute(
                        """
                        SELECT 1 FROM workers
                        WHERE user_id = %s AND COALESCE(status, 'new') <> %s
                        LIMIT 1
                        """,
                        (ids[0], WORKER_STATUS_REJECTED),
                    )
                else:
                    cur.execute(
                        """
                        SELECT 1 FROM workers
                        WHERE user_id IN (%s, %s) AND COALESCE(status, 'new') <> %s
                        LIMIT 1
                        """,
                        (ids[0], ids[1], WORKER_STATUS_REJECTED),
                    )
                return bool(cur.fetchone())
    except Exception:
        logger.exception("has_max_active_executor_profile max_uid=%s", max_user_id)
    return False


def get_max_worker_display_name(max_user_id: int) -> str:
    ids = _worker_lookup_ids_for_max(int(max_user_id))
    preferred = ids[0]
    if not DATABASE_URL:
        return ""
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                if len(ids) == 1:
                    cur.execute(
                        "SELECT full_name FROM workers WHERE user_id = %s LIMIT 1",
                        (ids[0],),
                    )
                else:
                    cur.execute(
                        """
                        SELECT full_name
                        FROM workers
                        WHERE user_id IN (%s, %s)
                        ORDER BY CASE WHEN user_id = %s THEN 0 ELSE 1 END
                        LIMIT 1
                        """,
                        (ids[0], ids[1], preferred),
                    )
                row = cur.fetchone()
                if row and row[0]:
                    return str(row[0]).strip()
                if len(ids) == 1:
                    cur.execute(
                        "SELECT full_name FROM users WHERE tg_id = %s LIMIT 1",
                        (ids[0],),
                    )
                else:
                    cur.execute(
                        """
                        SELECT full_name
                        FROM users
                        WHERE tg_id IN (%s, %s)
                        ORDER BY CASE WHEN tg_id = %s THEN 0 ELSE 1 END
                        LIMIT 1
                        """,
                        (ids[0], ids[1], preferred),
                    )
                row = cur.fetchone()
                return str(row[0]).strip() if row and row[0] else ""
    except Exception:
        logger.exception("get_max_worker_display_name")
    return ""


def save_max_visit_client_verified(max_user_id: int, username: str, data: dict[str, Any]) -> bool:
    uid = int(max_user_id)
    un = (username or "").strip()
    cn = (data.get("company_name") or "").strip()
    contact = (data.get("contact_name") or "").strip()
    pos = (data.get("position_in_org") or "").strip()
    phone = (data.get("phone") or "").strip()
    inn = (data.get("inn") or "").strip()
    cemail = (data.get("contact_email") or "").strip()
    save_data = {
        "company_name": cn,
        "contact_name": contact,
        "position_in_org": pos,
        "phone": phone,
        "inn": inn,
        "canonical_user_tg_id": data.get("canonical_user_tg_id"),
    }
    if not DATABASE_URL:
        logger.error(
            "save_max_visit_client_verified aborted: DATABASE_URL missing max_uid=%s",
            uid,
        )
        return False
    tg_row: int | None = None
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                tg_row = _client_tg_id_for_max_cp(uid, phone=phone or None, data=save_data)
                inn_digits = re.sub(r"\D", "", inn)
                inn_sql = inn_digits if len(inn_digits) in (10, 12) else ""
                company_id: int | None = None
                try:
                    company_id = _ensure_company_for_max_client(cur, cn, inn_sql)
                except Exception:
                    logger.exception(
                        "save_max_visit_client_verified company bind failed max_uid=%s",
                        uid,
                    )
                    company_id = None
                _upsert_users_row_for_max_visit_client(
                    cur,
                    tg_row=tg_row,
                    max_user_id=uid,
                    data=save_data,
                    company_id=company_id,
                )
                cur.execute("SAVEPOINT sp_agency_max_visit_clients")
                try:
                    cur.execute(
                        """
                        INSERT INTO agency_max_visit_clients (
                            max_user_id, username, company_name, contact_name, position_in_org,
                            phone, inn, contact_email, verified_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL)
                        ON CONFLICT (max_user_id) DO UPDATE SET
                            username = EXCLUDED.username,
                            company_name = EXCLUDED.company_name,
                            contact_name = EXCLUDED.contact_name,
                            position_in_org = EXCLUDED.position_in_org,
                            phone = EXCLUDED.phone,
                            inn = EXCLUDED.inn,
                            contact_email = EXCLUDED.contact_email,
                            verified_at = NULL
                        """,
                        (uid, un, cn, contact, pos, phone, inn, cemail),
                    )
                    cur.execute("RELEASE SAVEPOINT sp_agency_max_visit_clients")
                except Exception as exc:
                    if not _pg_undefined_column(exc):
                        cur.execute("ROLLBACK TO SAVEPOINT sp_agency_max_visit_clients")
                        raise
                    cur.execute("ROLLBACK TO SAVEPOINT sp_agency_max_visit_clients")
                    logger.warning(
                        "save_max_visit_client_verified agency_max without contact_email max_uid=%s",
                        uid,
                    )
                    cur.execute(
                        """
                        INSERT INTO agency_max_visit_clients (
                            max_user_id, username, company_name, contact_name, position_in_org, phone, inn, verified_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, NULL)
                        ON CONFLICT (max_user_id) DO UPDATE SET
                            username = EXCLUDED.username,
                            company_name = EXCLUDED.company_name,
                            contact_name = EXCLUDED.contact_name,
                            position_in_org = EXCLUDED.position_in_org,
                            phone = EXCLUDED.phone,
                            inn = EXCLUDED.inn,
                            verified_at = NULL
                        """,
                        (uid, un, cn, contact, pos, phone, inn),
                    )
                _upsert_visit_clients_profile_pg(cur, tg_row, cn, contact, phone, cemail)
                cur.execute(
                    """
                    INSERT INTO clients (user_id, company_name, contact_name, phone, registered_at)
                    VALUES (%s, %s, %s, %s, NOW())
                    ON CONFLICT (user_id) DO UPDATE SET
                        company_name = EXCLUDED.company_name,
                        contact_name = EXCLUDED.contact_name,
                        phone = EXCLUDED.phone
                    """,
                    (tg_row, cn, contact, phone),
                )
        return True
    except Exception:
        logger.exception("save_max_visit_client_verified pg max_uid=%s tg_id=%s", uid, tg_row)
    logger.error(
        "save_max_visit_client_verified aborted: postgres write failed max_uid=%s",
        uid,
    )
    return False


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
                (worker_tg_id_for_max(int(max_user_id)), username, payload_json),
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
                (worker_tg_id_for_max(int(max_user_id)), username, payload_s),
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
        _sync_urgent_crm_card_from_max_visit_order(int(max_user_id), base, int(pg_id))
        _sync_kp_crm_card_for_visit_order(int(max_user_id), base, int(pg_id))
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
    tg = resolve_tg_id_for_max_user(int(max_user_id))
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, payload, created_at
                FROM agency_visit_orders
                WHERE user_id IN (%s, %s)
                ORDER BY id DESC
                LIMIT %s
                """,
                (tg, int(max_user_id), lim),
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


_KP_STAGES_ADMIN = frozenset(
    {"new", "kp_prep", "client_review", "invoice_issued", "invoice_paid", "approved_project", "closed_lost"}
)
_URGENT_STAGES_ADMIN = frozenset(
    {"new", "manager_work", "invoice_issued", "invoice_paid", "project_active", "done", "cancelled"}
)


def _map_urgent_crm_stage_to_visit_order_status(crm_stage: str | None) -> str | None:
    key = (crm_stage or "").strip().lower()
    return {
        "new": "new",
        "manager_work": "processing",
        "invoice_issued": "awaiting_payment",
        "invoice_paid": "paid",
        "project_active": "project_created",
        "done": "project_created",
        "cancelled": "cancelled",
    }.get(key)


def _map_kp_crm_stage_to_visit_order_status(crm_stage: str | None) -> str | None:
    key = (crm_stage or "").strip().lower()
    return {
        "new": "new",
        "kp_prep": "processing",
        "client_review": "processing",
        "invoice_issued": "awaiting_payment",
        "invoice_paid": "paid",
        "approved_project": "project_created",
        "closed_lost": "cancelled",
    }.get(key)


def _status_column_exists() -> bool:
    if not DATABASE_URL:
        return False
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'agency_visit_orders'
                      AND column_name = 'status'
                    LIMIT 1
                    """
                )
                return bool(cur.fetchone())
    except Exception:
        logger.debug("_status_column_exists failed", exc_info=True)
        return False


def count_agency_visit_orders_funnel_excluding(
    *,
    exclude_statuses: tuple[str, ...] = ("project_created",),
    order_kind: str | None = None,
    stage: str | None = None,
) -> int:
    if not DATABASE_URL:
        return 0
    kind = (order_kind or "").strip()
    stage_filter = (stage or "").strip().lower()
    statuses = [str(s or "").strip() for s in exclude_statuses if str(s or "").strip()]
    has_status = _status_column_exists()
    where_parts: list[str] = []
    params: list[Any] = []
    if kind == "__urgent__":
        where_parts.append("COALESCE(payload->>'order_kind', 'quick_estimate') <> 'cp_request'")
    elif kind:
        where_parts.append("COALESCE(payload->>'order_kind', 'quick_estimate') = %s")
        params.append(kind)
    if has_status and statuses:
        where_parts.append("NOT (COALESCE(status, 'new') = ANY(%s))")
        params.append(statuses)
    if stage_filter and stage_filter != "all":
        where_parts.append("COALESCE(card.stage, 'new') = %s")
        params.append(stage_filter)
    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT COUNT(*)::int
                    FROM agency_visit_orders o
                    LEFT JOIN agency_crm_cards card
                      ON card.source_kind = 'agency_visit_order' AND card.source_id = o.id
                    {where_sql}
                    """,
                    tuple(params),
                )
                row = cur.fetchone()
                return int((row or [0])[0] or 0)
    except Exception:
        logger.exception("count_agency_visit_orders_funnel_excluding failed")
        return 0


def list_agency_visit_orders_funnel_page(
    *,
    exclude_statuses: tuple[str, ...] = ("project_created",),
    order_kind: str | None = None,
    stage: str | None = None,
    limit: int = 15,
    offset: int = 0,
) -> list[dict[str, Any]]:
    if not DATABASE_URL:
        return []
    lim = max(1, min(int(limit), 50))
    off = max(0, int(offset))
    kind = (order_kind or "").strip()
    stage_filter = (stage or "").strip().lower()
    statuses = [str(s or "").strip() for s in exclude_statuses if str(s or "").strip()]
    has_status = _status_column_exists()
    where_parts: list[str] = []
    params: list[Any] = []
    if kind == "__urgent__":
        where_parts.append("COALESCE(payload->>'order_kind', 'quick_estimate') <> 'cp_request'")
    elif kind:
        where_parts.append("COALESCE(payload->>'order_kind', 'quick_estimate') = %s")
        params.append(kind)
    if has_status and statuses:
        where_parts.append("NOT (COALESCE(status, 'new') = ANY(%s))")
        params.append(statuses)
    if stage_filter and stage_filter != "all":
        where_parts.append("COALESCE(card.stage, 'new') = %s")
        params.append(stage_filter)
    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    select_status = "COALESCE(o.status, 'new')" if has_status else "'new'"
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT o.id, o.user_id, o.username, o.payload, {select_status} AS status, o.created_at
                    FROM agency_visit_orders o
                    LEFT JOIN agency_crm_cards card
                      ON card.source_kind = 'agency_visit_order' AND card.source_id = o.id
                    {where_sql}
                    ORDER BY o.created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    tuple(params + [lim, off]),
                )
                rows = cur.fetchall() or []
    except Exception:
        logger.exception("list_agency_visit_orders_funnel_page failed")
        return []
    out: list[dict[str, Any]] = []
    for rid, user_id, username, payload, status, created_at in rows:
        p = payload if isinstance(payload, dict) else {}
        if not isinstance(p, dict):
            p = {}
        out.append(
            {
                "id": int(rid or 0),
                "user_id": int(user_id or 0) if user_id is not None else 0,
                "username": str(username or ""),
                "payload": p,
                "status": str(status or "new").strip() or "new",
                "created_at": created_at,
            }
        )
    return out


def get_agency_visit_order_for_admin(order_id: int) -> dict[str, Any] | None:
    if not DATABASE_URL:
        return None
    oid = int(order_id)
    if oid <= 0:
        return None
    has_status = _status_column_exists()
    select_status = "COALESCE(status, 'new')" if has_status else "'new'"
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id, user_id, username, payload, {select_status} AS status, created_at
                    FROM agency_visit_orders
                    WHERE id = %s
                    LIMIT 1
                    """,
                    (oid,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                rid, user_id, username, payload, status, created_at = row
    except Exception:
        logger.exception("get_agency_visit_order_for_admin failed order_id=%s", oid)
        return None
    p = payload if isinstance(payload, dict) else {}
    if not isinstance(p, dict):
        p = {}
    return {
        "id": int(rid or 0),
        "user_id": int(user_id or 0) if user_id is not None else 0,
        "username": str(username or ""),
        "payload": p,
        "status": str(status or "new").strip() or "new",
        "created_at": created_at,
    }


def get_agency_crm_card_pipeline_stage(order_id: int) -> tuple[str, str] | None:
    oid = int(order_id)
    if oid <= 0 or not DATABASE_URL:
        return None
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT pipeline, stage
                    FROM agency_crm_cards
                    WHERE source_kind = 'agency_visit_order' AND source_id = %s
                    LIMIT 1
                    """,
                    (oid,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                pl = str(row[0] or "").strip()
                st = str(row[1] or "").strip()
                if not pl or not st:
                    return None
                return pl, st
    except Exception:
        logger.debug("get_agency_crm_card_pipeline_stage failed order_id=%s", oid, exc_info=True)
        return None


def apply_visit_order_crm_stage_from_admin(order_id: int, target_stage: str) -> tuple[bool, str]:
    oid = int(order_id)
    ts = (target_stage or "").strip().lower()
    if oid <= 0 or not ts:
        return False, "Некорректные параметры."
    if not DATABASE_URL:
        return False, "Нужен PostgreSQL."
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT user_id, payload
                    FROM agency_visit_orders
                    WHERE id = %s
                    LIMIT 1
                    """,
                    (oid,),
                )
                row = cur.fetchone()
                if not row:
                    return False, "Заявка не найдена."
                user_id, payload = row
                data = payload if isinstance(payload, dict) else {}
                if not isinstance(data, dict):
                    data = {}
                kind = (data.get("order_kind") or "").strip()
                pipeline = "kp" if kind == "cp_request" else "urgent"
                allowed = _KP_STAGES_ADMIN if pipeline == "kp" else _URGENT_STAGES_ADMIN
                if ts not in allowed:
                    return False, f"Стадия «{ts}» недопустима для воронки {pipeline}."
                visit_status = (
                    _map_kp_crm_stage_to_visit_order_status(ts)
                    if pipeline == "kp"
                    else _map_urgent_crm_stage_to_visit_order_status(ts)
                )
                if not visit_status:
                    return False, "Не удалось сопоставить стадию со статусом заявки."
                has_status = _status_column_exists()
                if has_status:
                    cur.execute(
                        "UPDATE agency_visit_orders SET status = %s WHERE id = %s",
                        (visit_status, oid),
                    )
                et = (data.get("event_type") or "").strip()
                city = (data.get("city") or "").strip()
                title = (f"{et} · {city}" if et and city else (et or f"Заявка #{oid}"))[:2000]
                cur.execute(
                    """
                    INSERT INTO agency_crm_cards (
                        pipeline, stage, source_kind, source_id, client_tg_id, title, created_at, updated_at
                    )
                    VALUES (%s, %s, 'agency_visit_order', %s, %s, %s, NOW(), NOW())
                    ON CONFLICT (source_kind, source_id) DO UPDATE SET
                        pipeline = EXCLUDED.pipeline,
                        stage = EXCLUDED.stage,
                        client_tg_id = COALESCE(EXCLUDED.client_tg_id, agency_crm_cards.client_tg_id),
                        title = COALESCE(NULLIF(EXCLUDED.title, ''), agency_crm_cards.title),
                        updated_at = NOW()
                    """,
                    (pipeline, ts, oid, int(user_id or 0), title),
                )
                return True, f"{pipeline}: {ts} · статус заявки: {visit_status}"
    except Exception:
        logger.exception("apply_visit_order_crm_stage_from_admin failed order_id=%s stage=%s", oid, ts)
        return False, "Ошибка записи в БД."


def _hrm_card_title_from_join_payload(data: dict[str, Any], join_id: int) -> str:
    fn = (data.get("full_name") or "").strip()
    pos = (data.get("position") or "").strip()
    if fn and pos:
        return (f"{fn} · {pos}")[:2000]
    if fn:
        return fn[:2000]
    return f"Заявка в команду #{join_id}"


def _sync_hrm_crm_card_for_join_request(
    join_id: int, user_tg_id: int, *, stage: str, payload_dict: dict[str, Any]
) -> None:
    if not DATABASE_URL:
        return
    title = _hrm_card_title_from_join_payload(payload_dict, int(join_id))
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agency_crm_cards (
                        pipeline, stage, source_kind, source_id, client_tg_id, title, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
                    ON CONFLICT (source_kind, source_id) DO UPDATE SET
                        pipeline = EXCLUDED.pipeline,
                        stage = EXCLUDED.stage,
                        client_tg_id = COALESCE(EXCLUDED.client_tg_id, agency_crm_cards.client_tg_id),
                        title = COALESCE(NULLIF(EXCLUDED.title, ''), agency_crm_cards.title),
                        updated_at = NOW()
                    """,
                    (_HRM_PIPELINE, stage, _HRM_JOIN_SOURCE, int(join_id), int(user_tg_id), title),
                )
    except Exception:
        logger.warning(
            "sync_hrm_crm_card_for_join_request failed join_id=%s", join_id, exc_info=True
        )


def save_visit_join(max_user_id: int, username: str, payload_json: str) -> int | None:
    """Заявка в команду + users/workers (pending_review), user_id = synthetic tg_id."""
    if not DATABASE_URL:
        return None
    try:
        data = json.loads(payload_json) if isinstance(payload_json, str) else dict(payload_json)
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    data["cooperation_mode"] = normalize_cooperation_mode(data.get("cooperation_mode"))
    phone = (data.get("phone") or "").strip()
    tg_id = int(data.get("canonical_user_tg_id") or 0) or worker_tg_id_for_max(int(max_user_id))
    if phone and not data.get("canonical_user_tg_id"):
        tg_id = _client_tg_id_for_max_cp(int(max_user_id), phone=phone, data=data)
    full_name = (data.get("full_name") or "").strip()
    position = (data.get("position") or "").strip()
    try:
        pay_tier = int(data.get("experience_base_stars", 3))
    except (TypeError, ValueError):
        pay_tier = 3
    pay_tier = max(0, min(5, pay_tier))
    base_rating = float(pay_tier) if pay_tier >= 1 else 3.0
    city_sql = (data.get("city") or "").strip() or None
    metro_sql = (data.get("metro_station") or "").strip() or None
    selfie_ref = (str(data.get("selfie_url") or "")).strip() or None
    payload_s = json.dumps(data, ensure_ascii=False, default=str)
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agency_visit_join_requests (source, user_id, username, payload)
                VALUES ('max', %s, %s, %s::jsonb)
                RETURNING id
                """,
                (tg_id, username, payload_s),
            )
            row = cur.fetchone()
            request_id = int(row[0]) if row else None
            if not request_id:
                return None
            cur.execute(
                """
                INSERT INTO users (
                    tg_id, max_user_id, role, full_name, phone, profession, rating,
                    city, metro_station, selfie_photo_url, created_at, updated_at
                ) VALUES (%s, %s, 'worker', %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (tg_id) DO UPDATE SET
                    max_user_id = COALESCE(EXCLUDED.max_user_id, users.max_user_id),
                    full_name = EXCLUDED.full_name,
                    phone = EXCLUDED.phone,
                    profession = EXCLUDED.profession,
                    rating = EXCLUDED.rating,
                    city = EXCLUDED.city,
                    metro_station = EXCLUDED.metro_station,
                    selfie_photo_url = COALESCE(
                        NULLIF(BTRIM(EXCLUDED.selfie_photo_url), ''), users.selfie_photo_url
                    ),
                    updated_at = NOW()
                """,
                (
                    tg_id,
                    int(max_user_id),
                    full_name,
                    phone,
                    position,
                    base_rating,
                    city_sql,
                    metro_sql,
                    selfie_ref,
                ),
            )
            cur.execute(
                """
                INSERT INTO workers (
                    user_id, full_name, phone, profession, status, rating,
                    compensation_pay_tier, cooperation_mode, registered_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (user_id) DO UPDATE SET
                    full_name = EXCLUDED.full_name,
                    phone = EXCLUDED.phone,
                    profession = EXCLUDED.profession,
                    status = EXCLUDED.status,
                    rating = EXCLUDED.rating,
                    compensation_pay_tier = EXCLUDED.compensation_pay_tier,
                    cooperation_mode = EXCLUDED.cooperation_mode
                """,
                (
                    tg_id,
                    full_name,
                    phone,
                    position,
                    WORKER_STATUS_PENDING_REVIEW,
                    base_rating,
                    pay_tier,
                    data["cooperation_mode"],
                ),
            )
    _sync_hrm_crm_card_for_join_request(request_id, tg_id, stage="new", payload_dict=data)
    return request_id


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


def get_worker_cooperation_mode_metrics() -> dict[str, int]:
    if not DATABASE_URL:
        return {"agency_workers": 0, "platform_workers": 0}
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COALESCE(cooperation_mode, 'agency') AS mode, COUNT(*)
                FROM workers
                GROUP BY 1
                """
            )
            rows = cur.fetchall() or []
    out = {"agency_workers": 0, "platform_workers": 0}
    for mode, cnt in rows:
        m = normalize_cooperation_mode(mode)
        if m == COOPERATION_MODE_PLATFORM:
            out["platform_workers"] += int(cnt or 0)
        else:
            out["agency_workers"] += int(cnt or 0)
    return out


def get_users_phone_duplicates_metrics(limit: int = 20) -> dict[str, Any]:
    """
    Диагностика дублей users.phone (по нормализованному номеру).
    Нужна для admin UI и безопасной ручной чистки хвостов.
    """
    safe_limit = max(1, min(int(limit or 20), 100))
    if not DATABASE_URL:
        return {"duplicate_phones_total": 0, "duplicate_rows_total": 0, "sample": []}
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH norm AS (
                    SELECT
                        tg_id,
                        regexp_replace(COALESCE(phone, ''), '\\D', '', 'g') AS phone_norm
                    FROM users
                    WHERE COALESCE(btrim(phone), '') <> ''
                ),
                grouped AS (
                    SELECT
                        phone_norm,
                        COUNT(*)::int AS cnt,
                        array_agg(tg_id ORDER BY tg_id) AS tg_ids
                    FROM norm
                    WHERE phone_norm <> ''
                    GROUP BY phone_norm
                    HAVING COUNT(*) > 1
                )
                SELECT
                    (SELECT COUNT(*)::int FROM grouped) AS duplicate_phones_total,
                    (SELECT COALESCE(SUM(cnt), 0)::int FROM grouped) AS duplicate_rows_total
                """
            )
            row = cur.fetchone()
            duplicate_phones_total = int(row[0] or 0) if row else 0
            duplicate_rows_total = int(row[1] or 0) if row else 0
            cur.execute(
                """
                WITH norm AS (
                    SELECT
                        tg_id,
                        regexp_replace(COALESCE(phone, ''), '\\D', '', 'g') AS phone_norm
                    FROM users
                    WHERE COALESCE(btrim(phone), '') <> ''
                )
                SELECT
                    phone_norm,
                    COUNT(*)::int AS cnt,
                    array_agg(tg_id ORDER BY tg_id) AS tg_ids
                FROM norm
                WHERE phone_norm <> ''
                GROUP BY phone_norm
                HAVING COUNT(*) > 1
                ORDER BY cnt DESC, phone_norm
                LIMIT %s
                """,
                (safe_limit,),
            )
            rows = cur.fetchall() or []
    sample = [
        {
            "phone_norm": str(r[0] or ""),
            "cnt": int(r[1] or 0),
            "tg_ids": [int(v) for v in (r[2] or [])],
        }
        for r in rows
    ]
    return {
        "duplicate_phones_total": duplicate_phones_total,
        "duplicate_rows_total": duplicate_rows_total,
        "sample": sample,
    }


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


def list_open_shifts_admin_max(limit: int = 30) -> list[dict[str, Any]]:
    if not DATABASE_URL:
        return []
    lim = max(1, min(int(limit), 100))
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT s.id, s.shift_date, s.start_time, s.end_time, p.name, s.status,
                           COALESCE(s.workers_needed, 0), COALESCE(s.rate, 0), COALESCE(s.location, ''),
                           COALESCE(COUNT(sa.id), 0) AS assignments_total
                    FROM shifts s
                    JOIN projects p ON s.project_id = p.id
                    LEFT JOIN shift_assignments sa ON sa.shift_id = s.id
                    WHERE s.status IN ('open', 'in_progress')
                    GROUP BY s.id, s.shift_date, s.start_time, s.end_time, p.name, s.status, s.workers_needed, s.rate, s.location
                    ORDER BY s.shift_date DESC, s.id DESC
                    LIMIT %s
                    """,
                    (lim,),
                )
                rows = cur.fetchall() or []
    except Exception:
        logger.exception("list_open_shifts_admin_max failed")
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": int(r[0] or 0),
                "shift_date": str(r[1] or ""),
                "start_time": str(r[2] or ""),
                "end_time": str(r[3] or ""),
                "project_name": str(r[4] or ""),
                "status": str(r[5] or ""),
                "workers_needed": int(r[6] or 0),
                "rate": int(r[7] or 0),
                "location": str(r[8] or ""),
                "assignments_total": int(r[9] or 0),
            }
        )
    return out


def get_shift_admin_max(shift_id: int) -> dict[str, Any] | None:
    if not DATABASE_URL:
        return None
    sid = int(shift_id)
    if sid <= 0:
        return None
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT s.id, s.project_id, p.name, s.shift_date, s.start_time, s.end_time,
                           COALESCE(s.location, ''), COALESCE(s.rate, 0), COALESCE(s.workers_needed, 0),
                           COALESCE(s.status, ''), COALESCE(COUNT(sa.id), 0)
                    FROM shifts s
                    JOIN projects p ON p.id = s.project_id
                    LEFT JOIN shift_assignments sa ON sa.shift_id = s.id
                    WHERE s.id = %s
                    GROUP BY s.id, s.project_id, p.name, s.shift_date, s.start_time, s.end_time, s.location, s.rate, s.workers_needed, s.status
                    LIMIT 1
                    """,
                    (sid,),
                )
                row = cur.fetchone()
    except Exception:
        logger.exception("get_shift_admin_max failed shift_id=%s", sid)
        return None
    if not row:
        return None
    return {
        "id": int(row[0] or 0),
        "project_id": int(row[1] or 0),
        "project_name": str(row[2] or ""),
        "shift_date": str(row[3] or ""),
        "start_time": str(row[4] or ""),
        "end_time": str(row[5] or ""),
        "location": str(row[6] or ""),
        "rate": int(row[7] or 0),
        "workers_needed": int(row[8] or 0),
        "status": str(row[9] or ""),
        "assignments_total": int(row[10] or 0),
    }


def list_projects_admin_max(limit: int = 30) -> list[dict[str, Any]]:
    if not DATABASE_URL:
        return []
    lim = max(1, min(int(limit), 120))
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT p.id, p.name, p.company_id, COALESCE(c.name, '')
                    FROM projects p
                    LEFT JOIN companies c ON c.id = p.company_id
                    ORDER BY p.created_at DESC
                    LIMIT %s
                    """,
                    (lim,),
                )
                rows = cur.fetchall() or []
    except Exception:
        logger.exception("list_projects_admin_max failed")
        return []
    return [
        {
            "id": int(r[0] or 0),
            "name": str(r[1] or ""),
            "company_id": int(r[2] or 0) if r[2] is not None else 0,
            "company_name": str(r[3] or ""),
        }
        for r in rows
    ]


def get_project_admin_max(project_id: int) -> dict[str, Any] | None:
    if not DATABASE_URL:
        return None
    pid = int(project_id)
    if pid <= 0:
        return None
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT p.id, p.name, p.company_id, COALESCE(c.name, ''),
                           COALESCE(COUNT(s.id), 0) AS shifts_total,
                           COALESCE(SUM(CASE WHEN s.status IN ('open', 'in_progress') THEN 1 ELSE 0 END), 0) AS shifts_open
                    FROM projects p
                    LEFT JOIN companies c ON c.id = p.company_id
                    LEFT JOIN shifts s ON s.project_id = p.id
                    WHERE p.id = %s
                    GROUP BY p.id, p.name, p.company_id, c.name
                    LIMIT 1
                    """,
                    (pid,),
                )
                row = cur.fetchone()
    except Exception:
        logger.exception("get_project_admin_max failed project_id=%s", pid)
        return None
    if not row:
        return None
    return {
        "id": int(row[0] or 0),
        "name": str(row[1] or ""),
        "company_id": int(row[2] or 0) if row[2] is not None else 0,
        "company_name": str(row[3] or ""),
        "shifts_total": int(row[4] or 0),
        "shifts_open": int(row[5] or 0),
    }


def list_shift_assignments_for_shift_max(shift_id: int, limit: int = 100) -> list[dict[str, Any]]:
    if not DATABASE_URL:
        return []
    _ensure_shift_action_source_columns_max()
    sid = int(shift_id)
    lim = max(1, min(int(limit), 300))
    if sid <= 0:
        return []
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        """
                        SELECT sa.id, sa.worker_tg_id, COALESCE(w.full_name, ''), COALESCE(sa.status, ''),
                               sa.checkin_time, sa.checkout_time, COALESCE(sa.worked_minutes, 0),
                               COALESCE(sa.last_action_source, ''), sa.last_action_at
                        FROM shift_assignments sa
                        LEFT JOIN workers w ON w.user_id = sa.worker_tg_id
                        WHERE sa.shift_id = %s
                        ORDER BY sa.id DESC
                        LIMIT %s
                        """,
                        (sid, lim),
                    )
                except Exception:
                    cur.execute(
                        """
                        SELECT sa.id, sa.worker_tg_id, COALESCE(w.full_name, ''), COALESCE(sa.status, ''),
                               sa.checkin_time, sa.checkout_time, COALESCE(sa.worked_minutes, 0)
                        FROM shift_assignments sa
                        LEFT JOIN workers w ON w.user_id = sa.worker_tg_id
                        WHERE sa.shift_id = %s
                        ORDER BY sa.id DESC
                        LIMIT %s
                        """,
                        (sid, lim),
                    )
                rows = cur.fetchall() or []
    except Exception:
        logger.exception("list_shift_assignments_for_shift_max failed shift_id=%s", sid)
        return []
    return [
        {
            "id": int(r[0] or 0),
            "worker_tg_id": int(r[1] or 0),
            "worker_name": str(r[2] or ""),
            "status": str(r[3] or ""),
            "checkin_time": r[4],
            "checkout_time": r[5],
            "worked_minutes": int(r[6] or 0),
            "last_action_source": str(r[7] or "") if len(r) > 7 else "",
            "last_action_at": r[8] if len(r) > 8 else None,
        }
        for r in rows
    ]


def list_assignable_workers_for_shift_max(shift_id: int, limit: int = 20) -> list[dict[str, Any]]:
    if not DATABASE_URL:
        return []
    sid = int(shift_id)
    lim = max(1, min(int(limit), 100))
    if sid <= 0:
        return []
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT w.user_id, COALESCE(w.full_name, ''), COALESCE(w.profession, ''), COALESCE(w.phone, '')
                    FROM workers w
                    WHERE LOWER(COALESCE(w.status, '')) = 'approved'
                      AND LOWER(COALESCE(w.cooperation_mode, 'agency')) = 'agency'
                      AND NOT EXISTS (
                        SELECT 1
                        FROM shift_assignments sa
                        WHERE sa.shift_id = %s AND sa.worker_tg_id = w.user_id
                      )
                    ORDER BY COALESCE(w.registered_at, NOW()) DESC, w.user_id DESC
                    LIMIT %s
                    """,
                    (sid, lim),
                )
                rows = cur.fetchall() or []
    except Exception:
        logger.exception("list_assignable_workers_for_shift_max failed shift_id=%s", sid)
        return []
    return [
        {
            "user_id": int(r[0] or 0),
            "full_name": str(r[1] or ""),
            "profession": str(r[2] or ""),
            "phone": str(r[3] or ""),
        }
        for r in rows
        if int(r[0] or 0) > 0
    ]


def assign_worker_to_shift_max(shift_id: int, worker_tg_id: int) -> tuple[bool, str]:
    if not DATABASE_URL:
        return False, "Нужен PostgreSQL."
    sid = int(shift_id)
    wid = int(worker_tg_id)
    if sid <= 0 or wid <= 0:
        return False, "Некорректные параметры."
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM shifts WHERE id = %s LIMIT 1", (sid,))
                if not cur.fetchone():
                    return False, "Смена не найдена."
                cur.execute(
                    """
                    SELECT 1
                    FROM workers
                    WHERE user_id = %s
                      AND LOWER(COALESCE(status, '')) = 'approved'
                      AND LOWER(COALESCE(cooperation_mode, 'agency')) = 'agency'
                    LIMIT 1
                    """,
                    (wid,),
                )
                if not cur.fetchone():
                    return False, "Исполнитель не готов для агентских смен."
                cur.execute(
                    """
                    INSERT INTO shift_assignments (shift_id, worker_tg_id, status, created_at)
                    VALUES (%s, %s, 'assigned', NOW())
                    ON CONFLICT (shift_id, worker_tg_id) DO NOTHING
                    """,
                    (sid, wid),
                )
                if int(cur.rowcount or 0) <= 0:
                    return False, "Исполнитель уже назначен на эту смену."
        return True, "Исполнитель назначен."
    except Exception:
        logger.exception("assign_worker_to_shift_max failed shift_id=%s worker=%s", sid, wid)
        return False, "Ошибка записи в БД."


def list_shift_assignments_recent_max(limit: int = 30) -> list[dict[str, Any]]:
    if not DATABASE_URL:
        return []
    lim = max(1, min(int(limit), 200))
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT sa.id, sa.shift_id, sa.worker_tg_id, COALESCE(sa.status, ''),
                           COALESCE(w.full_name, ''), s.shift_date, s.start_time, s.end_time
                    FROM shift_assignments sa
                    LEFT JOIN workers w ON w.user_id = sa.worker_tg_id
                    LEFT JOIN shifts s ON s.id = sa.shift_id
                    ORDER BY sa.id DESC
                    LIMIT %s
                    """,
                    (lim,),
                )
                rows = cur.fetchall() or []
    except Exception:
        logger.exception("list_shift_assignments_recent_max failed")
        return []
    return [
        {
            "id": int(r[0] or 0),
            "shift_id": int(r[1] or 0),
            "worker_tg_id": int(r[2] or 0),
            "status": str(r[3] or ""),
            "worker_name": str(r[4] or ""),
            "shift_date": str(r[5] or ""),
            "start_time": str(r[6] or ""),
            "end_time": str(r[7] or ""),
        }
        for r in rows
    ]


def list_worker_payments_recent_max(limit: int = 30) -> list[dict[str, Any]]:
    if not DATABASE_URL:
        return []
    lim = max(1, min(int(limit), 200))
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT wp.id, wp.worker_tg_id, wp.amount_rub, COALESCE(wp.currency, 'RUB'),
                           COALESCE(wp.status, ''), COALESCE(wp.title, ''), wp.shift_id, wp.created_at,
                           COALESCE(w.full_name, '')
                    FROM worker_payments wp
                    LEFT JOIN workers w ON w.user_id = wp.worker_tg_id
                    ORDER BY wp.created_at DESC, wp.id DESC
                    LIMIT %s
                    """,
                    (lim,),
                )
                rows = cur.fetchall() or []
    except Exception:
        logger.exception("list_worker_payments_recent_max failed")
        return []
    return [
        {
            "id": int(r[0] or 0),
            "worker_tg_id": int(r[1] or 0),
            "amount_rub": float(r[2] or 0),
            "currency": str(r[3] or "RUB"),
            "status": str(r[4] or ""),
            "title": str(r[5] or ""),
            "shift_id": int(r[6] or 0) if r[6] is not None else None,
            "created_at": r[7],
            "worker_name": str(r[8] or ""),
        }
        for r in rows
    ]


def get_worker_payment_admin_max(payment_id: int) -> dict[str, Any] | None:
    if not DATABASE_URL:
        return None
    pid = int(payment_id)
    if pid <= 0:
        return None
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT wp.id, wp.worker_tg_id, wp.amount_rub, COALESCE(wp.currency, 'RUB'),
                           COALESCE(wp.status, ''), COALESCE(wp.title, ''), COALESCE(wp.period_label, ''),
                           wp.shift_id, wp.paid_at, wp.created_at, COALESCE(wp.notes, ''),
                           COALESCE(w.full_name, '')
                    FROM worker_payments wp
                    LEFT JOIN workers w ON w.user_id = wp.worker_tg_id
                    WHERE wp.id = %s
                    LIMIT 1
                    """,
                    (pid,),
                )
                row = cur.fetchone()
    except Exception:
        logger.exception("get_worker_payment_admin_max failed payment_id=%s", pid)
        return None
    if not row:
        return None
    return {
        "id": int(row[0] or 0),
        "worker_tg_id": int(row[1] or 0),
        "amount_rub": float(row[2] or 0),
        "currency": str(row[3] or "RUB"),
        "status": str(row[4] or ""),
        "title": str(row[5] or ""),
        "period_label": str(row[6] or ""),
        "shift_id": int(row[7] or 0) if row[7] is not None else None,
        "paid_at": row[8],
        "created_at": row[9],
        "notes": str(row[10] or ""),
        "worker_name": str(row[11] or ""),
    }


def list_workers_admin_max(limit: int = 30) -> list[dict[str, Any]]:
    if not DATABASE_URL:
        return []
    lim = max(1, min(int(limit), 200))
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT user_id, COALESCE(full_name, ''), COALESCE(phone, ''), COALESCE(profession, ''),
                           COALESCE(status, 'new'), COALESCE(cooperation_mode, 'agency'),
                           COALESCE(rating, 0), COALESCE(registered_at, NOW())
                    FROM workers
                    ORDER BY registered_at DESC
                    LIMIT %s
                    """,
                    (lim,),
                )
                rows = cur.fetchall() or []
    except Exception:
        logger.exception("list_workers_admin_max failed")
        return []
    return [
        {
            "user_id": int(r[0] or 0),
            "full_name": str(r[1] or ""),
            "phone": str(r[2] or ""),
            "profession": str(r[3] or ""),
            "status": str(r[4] or "new"),
            "cooperation_mode": str(r[5] or "agency"),
            "rating": float(r[6] or 0),
            "registered_at": r[7],
        }
        for r in rows
    ]


def search_workers_admin_max(query: str, limit: int = 20) -> list[dict[str, Any]]:
    if not DATABASE_URL:
        return []
    raw = (query or "").strip()
    if not raw:
        return []
    lim = max(1, min(int(limit), 100))
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                if raw.isdigit():
                    cur.execute(
                        """
                        SELECT user_id, COALESCE(full_name, ''), COALESCE(phone, ''), COALESCE(profession, ''),
                               COALESCE(status, 'new'), COALESCE(cooperation_mode, 'agency'),
                               COALESCE(rating, 0), COALESCE(registered_at, NOW())
                        FROM workers
                        WHERE user_id = %s
                        LIMIT %s
                        """,
                        (int(raw), lim),
                    )
                else:
                    pat = f"%{raw}%"
                    cur.execute(
                        """
                        SELECT user_id, COALESCE(full_name, ''), COALESCE(phone, ''), COALESCE(profession, ''),
                               COALESCE(status, 'new'), COALESCE(cooperation_mode, 'agency'),
                               COALESCE(rating, 0), COALESCE(registered_at, NOW())
                        FROM workers
                        WHERE full_name ILIKE %s OR COALESCE(phone, '') ILIKE %s OR COALESCE(profession, '') ILIKE %s
                        ORDER BY registered_at DESC
                        LIMIT %s
                        """,
                        (pat, pat, pat, lim),
                    )
                rows = cur.fetchall() or []
    except Exception:
        logger.exception("search_workers_admin_max failed query=%r", raw)
        return []
    return [
        {
            "user_id": int(r[0] or 0),
            "full_name": str(r[1] or ""),
            "phone": str(r[2] or ""),
            "profession": str(r[3] or ""),
            "status": str(r[4] or "new"),
            "cooperation_mode": str(r[5] or "agency"),
            "rating": float(r[6] or 0),
            "registered_at": r[7],
        }
        for r in rows
    ]


def get_worker_admin_max(worker_id: int) -> dict[str, Any] | None:
    if not DATABASE_URL:
        return None
    wid = int(worker_id)
    if wid <= 0:
        return None
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT user_id, COALESCE(full_name, ''), COALESCE(phone, ''), COALESCE(profession, ''),
                           COALESCE(status, 'new'), COALESCE(cooperation_mode, 'agency'),
                           COALESCE(rating, 0), COALESCE(registered_at, NOW())
                    FROM workers
                    WHERE user_id = %s
                    LIMIT 1
                    """,
                    (wid,),
                )
                row = cur.fetchone()
                if not row:
                    return None
    except Exception:
        logger.exception("get_worker_admin_max failed worker_id=%s", wid)
        return None
    return {
        "user_id": int(row[0] or 0),
        "full_name": str(row[1] or ""),
        "phone": str(row[2] or ""),
        "profession": str(row[3] or ""),
        "status": str(row[4] or "new"),
        "cooperation_mode": str(row[5] or "agency"),
        "rating": float(row[6] or 0),
        "registered_at": row[7],
    }


def get_worker_assignment_stats_max(worker_id: int) -> dict[str, int]:
    if not DATABASE_URL:
        return {"assignments_total": 0, "open_tasks": 0}
    wid = int(worker_id)
    if wid <= 0:
        return {"assignments_total": 0, "open_tasks": 0}
    assignments_total = 0
    open_tasks = 0
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM shift_assignments WHERE worker_tg_id = %s", (wid,))
                assignments_total = int((cur.fetchone() or [0])[0] or 0)
                try:
                    cur.execute("SELECT COUNT(*) FROM tasks WHERE assigned_to = %s AND status <> 'completed'", (wid,))
                    open_tasks = int((cur.fetchone() or [0])[0] or 0)
                except Exception:
                    open_tasks = 0
    except Exception:
        logger.exception("get_worker_assignment_stats_max failed worker_id=%s", wid)
    return {"assignments_total": assignments_total, "open_tasks": open_tasks}


def list_worker_payments_for_worker_max(worker_tg_id: int, limit: int = 10) -> list[dict[str, Any]]:
    if not DATABASE_URL:
        return []
    wid = int(worker_tg_id)
    lim = max(1, min(int(limit), 100))
    if wid <= 0:
        return []
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, amount_rub, COALESCE(currency, 'RUB'), COALESCE(status, ''),
                           COALESCE(title, ''), COALESCE(period_label, ''), shift_id, paid_at, created_at
                    FROM worker_payments
                    WHERE worker_tg_id = %s
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s
                    """,
                    (wid, lim),
                )
                rows = cur.fetchall() or []
    except Exception:
        logger.exception("list_worker_payments_for_worker_max failed worker_id=%s", wid)
        return []
    return [
        {
            "id": int(r[0] or 0),
            "amount_rub": float(r[1] or 0),
            "currency": str(r[2] or "RUB"),
            "status": str(r[3] or ""),
            "title": str(r[4] or ""),
            "period_label": str(r[5] or ""),
            "shift_id": int(r[6] or 0) if r[6] is not None else None,
            "paid_at": r[7],
            "created_at": r[8],
        }
        for r in rows
    ]


def list_worker_shifts_max(worker_tg_id: int, limit: int = 20) -> list[dict[str, Any]]:
    if not DATABASE_URL:
        return []
    wid = int(worker_tg_id)
    lim = max(1, min(int(limit), 100))
    if wid <= 0:
        return []
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT s.id, s.shift_date, s.start_time, s.end_time, COALESCE(s.location, ''),
                           COALESCE(s.status, ''), COALESCE(sa.status, ''), COALESCE(p.name, '')
                    FROM shift_assignments sa
                    JOIN shifts s ON s.id = sa.shift_id
                    LEFT JOIN projects p ON p.id = s.project_id
                    WHERE sa.worker_tg_id = %s
                    ORDER BY s.shift_date DESC, s.id DESC
                    LIMIT %s
                    """,
                    (wid, lim),
                )
                rows = cur.fetchall() or []
    except Exception:
        logger.exception("list_worker_shifts_max failed worker=%s", wid)
        return []
    return [
        {
            "shift_id": int(r[0] or 0),
            "shift_date": str(r[1] or ""),
            "start_time": str(r[2] or ""),
            "end_time": str(r[3] or ""),
            "location": str(r[4] or ""),
            "shift_status": str(r[5] or ""),
            "assignment_status": str(r[6] or ""),
            "project_name": str(r[7] or ""),
        }
        for r in rows
    ]


def get_worker_shift_assignment_max(shift_id: int, worker_tg_id: int) -> dict[str, Any] | None:
    if not DATABASE_URL:
        return None
    sid = int(shift_id)
    wid = int(worker_tg_id)
    if sid <= 0 or wid <= 0:
        return None
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT s.id, s.shift_date, s.start_time, s.end_time, COALESCE(s.location, ''),
                           COALESCE(s.status, ''), COALESCE(p.name, ''), COALESCE(sa.status, ''),
                           sa.checkin_time, sa.checkout_time, COALESCE(sa.worked_minutes, 0)
                    FROM shift_assignments sa
                    JOIN shifts s ON s.id = sa.shift_id
                    LEFT JOIN projects p ON p.id = s.project_id
                    WHERE sa.shift_id = %s AND sa.worker_tg_id = %s
                    LIMIT 1
                    """,
                    (sid, wid),
                )
                row = cur.fetchone()
    except Exception:
        logger.exception("get_worker_shift_assignment_max failed shift=%s worker=%s", sid, wid)
        return None
    if not row:
        return None
    return {
        "shift_id": int(row[0] or 0),
        "shift_date": str(row[1] or ""),
        "start_time": str(row[2] or ""),
        "end_time": str(row[3] or ""),
        "location": str(row[4] or ""),
        "shift_status": str(row[5] or ""),
        "project_name": str(row[6] or ""),
        "assignment_status": str(row[7] or ""),
        "checkin_time": row[8],
        "checkout_time": row[9],
        "worked_minutes": int(row[10] or 0),
    }


def _set_assignment_last_action_max(cur, shift_id: int, worker_tg_id: int, *, source: str) -> None:
    src = (source or "").strip().lower()[:16] or "max"
    try:
        cur.execute(
            """
            UPDATE shift_assignments
            SET last_action_source = %s, last_action_at = NOW()
            WHERE shift_id = %s AND worker_tg_id = %s
            """,
            (src, int(shift_id), int(worker_tg_id)),
        )
    except Exception:
        pass


def _assignment_cross_source_guard_max(
    cur,
    shift_id: int,
    worker_tg_id: int,
    *,
    source: str,
    window_seconds: int = 8,
) -> bool:
    src = (source or "").strip().lower()[:16] or "max"
    try:
        cur.execute(
            """
            SELECT 1
            FROM shift_assignments
            WHERE shift_id = %s
              AND worker_tg_id = %s
              AND COALESCE(last_action_source, '') <> ''
              AND COALESCE(last_action_source, '') <> %s
              AND last_action_at IS NOT NULL
              AND EXTRACT(EPOCH FROM (NOW() - last_action_at)) < %s
            LIMIT 1
            """,
            (int(shift_id), int(worker_tg_id), src, max(1, int(window_seconds))),
        )
        return cur.fetchone() is None
    except Exception:
        return True


def confirm_worker_shift_max(shift_id: int, worker_tg_id: int) -> bool:
    if not DATABASE_URL:
        return False
    _ensure_shift_action_source_columns_max()
    sid = int(shift_id)
    wid = int(worker_tg_id)
    if sid <= 0 or wid <= 0:
        return False
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                if not _assignment_cross_source_guard_max(cur, sid, wid, source="max"):
                    return False
                cur.execute(
                    "UPDATE shift_assignments SET status = 'confirmed' WHERE shift_id = %s AND worker_tg_id = %s",
                    (sid, wid),
                )
                ok = int(cur.rowcount or 0) > 0
                if ok:
                    _set_assignment_last_action_max(cur, sid, wid, source="max")
                return ok
    except Exception:
        logger.exception("confirm_worker_shift_max failed shift=%s worker=%s", sid, wid)
        return False


def checkin_worker_shift_max(
    shift_id: int,
    worker_tg_id: int,
    *,
    photo_url: str | None = None,
    checkin_location: str | None = None,
) -> bool:
    if not DATABASE_URL:
        return False
    _ensure_shift_action_source_columns_max()
    sid = int(shift_id)
    wid = int(worker_tg_id)
    if sid <= 0 or wid <= 0:
        return False
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                if not _assignment_cross_source_guard_max(cur, sid, wid, source="max"):
                    return False
                try:
                    cur.execute(
                        """
                        UPDATE shift_assignments
                        SET status = 'checked_in',
                            checkin_time = NOW(),
                            checkin_photo_url = COALESCE(%s, checkin_photo_url),
                            checkin_location = COALESCE(%s, checkin_location)
                        WHERE shift_id = %s AND worker_tg_id = %s
                        """,
                        (photo_url, checkin_location, sid, wid),
                    )
                except Exception:
                    cur.execute(
                        """
                        UPDATE shift_assignments
                        SET status = 'checked_in',
                            checkin_time = NOW()
                        WHERE shift_id = %s AND worker_tg_id = %s
                        """,
                        (sid, wid),
                    )
                ok = int(cur.rowcount or 0) > 0
                if ok:
                    _set_assignment_last_action_max(cur, sid, wid, source="max")
                    cur.execute("UPDATE shifts SET status = 'in_progress' WHERE id = %s AND status = 'open'", (sid,))
                return ok
    except Exception:
        logger.exception("checkin_worker_shift_max failed shift=%s worker=%s", sid, wid)
        return False


def checkout_worker_shift_max(
    shift_id: int,
    worker_tg_id: int,
    *,
    photo_url: str | None = None,
    checkout_location: str | None = None,
) -> bool:
    if not DATABASE_URL:
        return False
    _ensure_shift_action_source_columns_max()
    sid = int(shift_id)
    wid = int(worker_tg_id)
    if sid <= 0 or wid <= 0:
        return False
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                if not _assignment_cross_source_guard_max(cur, sid, wid, source="max"):
                    return False
                cur.execute(
                    "SELECT checkin_time FROM shift_assignments WHERE shift_id = %s AND worker_tg_id = %s",
                    (sid, wid),
                )
                row = cur.fetchone()
                if not row or row[0] is None:
                    return False
                try:
                    cur.execute(
                        """
                        UPDATE shift_assignments
                        SET status = 'checked_out',
                            checkout_time = NOW(),
                            worked_minutes = GREATEST(EXTRACT(EPOCH FROM (NOW() - checkin_time))::int / 60, 0),
                            checkout_photo_url = COALESCE(%s, checkout_photo_url),
                            checkout_location = COALESCE(%s, checkout_location)
                        WHERE shift_id = %s AND worker_tg_id = %s
                        """,
                        (photo_url, checkout_location, sid, wid),
                    )
                except Exception:
                    cur.execute(
                        """
                        UPDATE shift_assignments
                        SET status = 'checked_out',
                            checkout_time = NOW(),
                            worked_minutes = GREATEST(EXTRACT(EPOCH FROM (NOW() - checkin_time))::int / 60, 0)
                        WHERE shift_id = %s AND worker_tg_id = %s
                        """,
                        (sid, wid),
                    )
                ok = int(cur.rowcount or 0) > 0
                if ok:
                    _set_assignment_last_action_max(cur, sid, wid, source="max")
                    cur.execute(
                        "SELECT COUNT(*) FROM shift_assignments WHERE shift_id = %s AND status NOT IN ('checked_out', 'cancelled')",
                        (sid,),
                    )
                    left = int((cur.fetchone() or [0])[0] or 0)
                    if left == 0:
                        cur.execute("UPDATE shifts SET status = 'closed' WHERE id = %s", (sid,))
                return ok
    except Exception:
        logger.exception("checkout_worker_shift_max failed shift=%s worker=%s", sid, wid)
        return False


def start_worker_break_max(shift_id: int, worker_tg_id: int, break_type: str) -> bool:
    if not DATABASE_URL:
        return False
    _ensure_shift_action_source_columns_max()
    sid = int(shift_id)
    wid = int(worker_tg_id)
    bt = (break_type or "").strip().lower()
    if sid <= 0 or wid <= 0 or bt not in {"lunch", "smoke", "tech"}:
        return False
    max_minutes = 30 if bt == "lunch" else 5 if bt == "smoke" else 10
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                if not _assignment_cross_source_guard_max(cur, sid, wid, source="max"):
                    return False
                cur.execute(
                    "SELECT 1 FROM assignment_breaks WHERE shift_id = %s AND worker_tg_id = %s AND ended_at IS NULL LIMIT 1",
                    (sid, wid),
                )
                if cur.fetchone():
                    return False
                cur.execute(
                    """
                    INSERT INTO assignment_breaks (shift_id, worker_tg_id, break_type, max_minutes)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (sid, wid, bt, max_minutes),
                )
                _set_assignment_last_action_max(cur, sid, wid, source="max")
                return True
    except Exception:
        logger.exception("start_worker_break_max failed shift=%s worker=%s", sid, wid)
        return False


def stop_worker_break_max(shift_id: int, worker_tg_id: int) -> bool:
    if not DATABASE_URL:
        return False
    _ensure_shift_action_source_columns_max()
    sid = int(shift_id)
    wid = int(worker_tg_id)
    if sid <= 0 or wid <= 0:
        return False
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE assignment_breaks SET ended_at = NOW() WHERE shift_id = %s AND worker_tg_id = %s AND ended_at IS NULL",
                    (sid, wid),
                )
                ok = int(cur.rowcount or 0) > 0
                if ok:
                    _set_assignment_last_action_max(cur, sid, wid, source="max")
                return ok
    except Exception:
        logger.exception("stop_worker_break_max failed shift=%s worker=%s", sid, wid)
        return False


def get_active_break_max(shift_id: int, worker_tg_id: int) -> dict[str, Any] | None:
    if not DATABASE_URL:
        return None
    sid = int(shift_id)
    wid = int(worker_tg_id)
    if sid <= 0 or wid <= 0:
        return None
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, break_type, started_at, max_minutes
                    FROM assignment_breaks
                    WHERE shift_id = %s AND worker_tg_id = %s AND ended_at IS NULL
                    ORDER BY started_at DESC
                    LIMIT 1
                    """,
                    (sid, wid),
                )
                row = cur.fetchone()
    except Exception:
        logger.exception("get_active_break_max failed shift=%s worker=%s", sid, wid)
        return None
    if not row:
        return None
    return {
        "id": int(row[0] or 0),
        "break_type": str(row[1] or ""),
        "started_at": row[2],
        "max_minutes": int(row[3] or 0),
    }


def get_worker_break_stats_max(shift_id: int, worker_tg_id: int) -> dict[str, int]:
    out = {"lunch_count": 0, "smoke_count": 0, "tech_count": 0, "total_minutes": 0}
    if not DATABASE_URL:
        return out
    sid = int(shift_id)
    wid = int(worker_tg_id)
    if sid <= 0 or wid <= 0:
        return out
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE break_type = 'lunch')::int,
                        COUNT(*) FILTER (WHERE break_type = 'smoke')::int,
                        COUNT(*) FILTER (WHERE break_type NOT IN ('lunch', 'smoke'))::int,
                        COALESCE(
                            SUM(GREATEST(EXTRACT(EPOCH FROM (COALESCE(ended_at, NOW()) - started_at)) / 60.0, 0)),
                            0
                        )::int
                    FROM assignment_breaks
                    WHERE shift_id = %s AND worker_tg_id = %s
                    """,
                    (sid, wid),
                )
                row = cur.fetchone()
                if row:
                    out = {
                        "lunch_count": int(row[0] or 0),
                        "smoke_count": int(row[1] or 0),
                        "tech_count": int(row[2] or 0),
                        "total_minutes": int(row[3] or 0),
                    }
    except Exception:
        logger.exception("get_worker_break_stats_max failed shift=%s worker=%s", sid, wid)
    return out


def auto_close_expired_breaks_max() -> int:
    if not DATABASE_URL:
        return 0
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE assignment_breaks
                    SET ended_at = NOW(), auto_closed = TRUE
                    WHERE ended_at IS NULL
                      AND started_at + (COALESCE(max_minutes, 10) || ' minutes')::interval <= NOW()
                    """
                )
                return int(cur.rowcount or 0)
    except Exception:
        logger.exception("auto_close_expired_breaks_max failed")
        return 0


def get_worker_beacon_state_max(worker_tg_id: int) -> dict[str, Any]:
    out = {"is_active": False, "enabled_at": None, "expires_at": None}
    if not DATABASE_URL:
        return out
    wid = int(worker_tg_id)
    if wid <= 0:
        return out
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT is_active, enabled_at, expires_at FROM worker_beacon WHERE worker_tg_id = %s LIMIT 1",
                    (wid,),
                )
                row = cur.fetchone()
                if row:
                    out = {
                        "is_active": bool(int(row[0] or 0)),
                        "enabled_at": row[1],
                        "expires_at": row[2],
                    }
    except Exception:
        logger.exception("get_worker_beacon_state_max failed worker=%s", wid)
    return out


def enable_worker_beacon_max(worker_tg_id: int, hours: int = 24) -> bool:
    if not DATABASE_URL:
        return False
    wid = int(worker_tg_id)
    hh = max(1, min(168, int(hours or 24)))
    if wid <= 0:
        return False
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO worker_beacon (worker_tg_id, is_active, enabled_at, expires_at, updated_at)
                    VALUES (%s, 1, NOW(), NOW() + (%s || ' hours')::interval, NOW())
                    ON CONFLICT (worker_tg_id) DO UPDATE SET
                        is_active = 1,
                        enabled_at = NOW(),
                        expires_at = NOW() + (%s || ' hours')::interval,
                        updated_at = NOW()
                    """,
                    (wid, hh, hh),
                )
                return True
    except Exception:
        logger.exception("enable_worker_beacon_max failed worker=%s", wid)
        return False


def disable_worker_beacon_max(worker_tg_id: int) -> bool:
    if not DATABASE_URL:
        return False
    wid = int(worker_tg_id)
    if wid <= 0:
        return False
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO worker_beacon (worker_tg_id, is_active, enabled_at, expires_at, updated_at)
                    VALUES (%s, 0, NULL, NULL, NOW())
                    ON CONFLICT (worker_tg_id) DO UPDATE SET
                        is_active = 0,
                        expires_at = NULL,
                        updated_at = NOW()
                    """,
                    (wid,),
                )
                return True
    except Exception:
        logger.exception("disable_worker_beacon_max failed worker=%s", wid)
        return False


def update_worker_payment_status_max(payment_id: int, status: str) -> tuple[bool, str]:
    if not DATABASE_URL:
        return False, "Нужен PostgreSQL."
    pid = int(payment_id)
    st = (status or "").strip().lower()
    if pid <= 0 or st not in {"pending", "approved", "paid", "cancelled"}:
        return False, "Некорректные параметры."
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                if st == "paid":
                    cur.execute(
                        "UPDATE worker_payments SET status = %s, paid_at = NOW() WHERE id = %s",
                        (st, pid),
                    )
                else:
                    cur.execute(
                        "UPDATE worker_payments SET status = %s, paid_at = NULL WHERE id = %s",
                        (st, pid),
                    )
                if int(cur.rowcount or 0) <= 0:
                    return False, "Выплата не найдена."
    except Exception:
        logger.exception("update_worker_payment_status_max failed payment_id=%s status=%s", pid, st)
        return False, "Ошибка записи в БД."
    return True, "Статус обновлён."


def _ensure_admin_logs_table_max(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_logs (
            id BIGSERIAL PRIMARY KEY,
            admin_user_id BIGINT NOT NULL,
            action TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id BIGINT,
            details TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
        """
    )


def log_admin_action_max(
    admin_user_id: int, action: str, entity_type: str, entity_id: int | None, details: str = ""
) -> None:
    if not DATABASE_URL:
        return
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                _ensure_admin_logs_table_max(cur)
                cur.execute(
                    """
                    INSERT INTO admin_logs (admin_user_id, action, entity_type, entity_id, details, created_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                    """,
                    (
                        int(admin_user_id),
                        (action or "").strip()[:120],
                        (entity_type or "").strip()[:80],
                        int(entity_id) if entity_id is not None else None,
                        (details or "").strip()[:1000],
                    ),
                )
    except Exception:
        logger.exception("log_admin_action_max failed action=%s entity=%s", action, entity_type)


def list_admin_logs_max(limit: int = 30) -> list[dict[str, Any]]:
    if not DATABASE_URL:
        return []
    lim = max(1, min(int(limit), 200))
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                _ensure_admin_logs_table_max(cur)
                cur.execute(
                    """
                    SELECT admin_user_id, action, entity_type, entity_id, details, created_at
                    FROM admin_logs
                    ORDER BY id DESC
                    LIMIT %s
                    """,
                    (lim,),
                )
                rows = cur.fetchall() or []
    except Exception:
        logger.exception("list_admin_logs_max failed")
        return []
    return [
        {
            "admin_user_id": int(r[0] or 0),
            "action": str(r[1] or ""),
            "entity_type": str(r[2] or ""),
            "entity_id": int(r[3] or 0) if r[3] is not None else None,
            "details": str(r[4] or ""),
            "created_at": r[5],
        }
        for r in rows
    ]


def get_admin_hub_counters_max() -> dict[str, int]:
    out = {
        "open_shifts": 0,
        "projects_total": 0,
        "payments_pending": 0,
        "crm_all": 0,
        "crm_kp": 0,
        "crm_urgent": 0,
        "workers_total": 0,
        "checked_in_now": 0,
        "on_break_now": 0,
    }
    if not DATABASE_URL:
        return out
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM shifts WHERE status IN ('open', 'in_progress')")
                out["open_shifts"] = int((cur.fetchone() or [0])[0] or 0)
                cur.execute("SELECT COUNT(*) FROM projects")
                out["projects_total"] = int((cur.fetchone() or [0])[0] or 0)
                cur.execute("SELECT COUNT(*) FROM worker_payments WHERE COALESCE(status, 'pending') = 'pending'")
                out["payments_pending"] = int((cur.fetchone() or [0])[0] or 0)
                cur.execute("SELECT COUNT(*) FROM workers")
                out["workers_total"] = int((cur.fetchone() or [0])[0] or 0)
                cur.execute("SELECT COUNT(*) FROM shift_assignments WHERE LOWER(COALESCE(status, '')) = 'checked_in'")
                out["checked_in_now"] = int((cur.fetchone() or [0])[0] or 0)
                try:
                    cur.execute("SELECT COUNT(*) FROM assignment_breaks WHERE ended_at IS NULL")
                    out["on_break_now"] = int((cur.fetchone() or [0])[0] or 0)
                except Exception:
                    out["on_break_now"] = 0
    except Exception:
        logger.exception("get_admin_hub_counters_max failed basic counters")
    try:
        out["crm_all"] = count_agency_visit_orders_funnel_excluding(order_kind=None)
        out["crm_kp"] = count_agency_visit_orders_funnel_excluding(order_kind="cp_request")
        out["crm_urgent"] = count_agency_visit_orders_funnel_excluding(order_kind="__urgent__")
    except Exception:
        logger.exception("get_admin_hub_counters_max failed crm counters")
    return out


def get_company_subscription_metrics_max(days: int = 7) -> dict[str, int]:
    out = {
        "active_total": 0,
        "expiring_soon": 0,
        "expired_total": 0,
        "without_subscription": 0,
    }
    if not DATABASE_URL:
        return out
    d = max(1, min(90, int(days or 7)))
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM company_subscriptions
                    WHERE LOWER(COALESCE(status, '')) IN ('active', 'trial', 'grace')
                      AND (ends_at IS NULL OR ends_at > NOW())
                    """
                )
                out["active_total"] = int((cur.fetchone() or [0])[0] or 0)
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM company_subscriptions
                    WHERE LOWER(COALESCE(status, '')) IN ('active', 'trial', 'grace')
                      AND ends_at IS NOT NULL
                      AND ends_at > NOW()
                      AND ends_at <= (NOW() + (%s || ' days')::interval)
                    """,
                    (d,),
                )
                out["expiring_soon"] = int((cur.fetchone() or [0])[0] or 0)
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM company_subscriptions
                    WHERE ends_at IS NOT NULL
                      AND ends_at <= NOW()
                    """
                )
                out["expired_total"] = int((cur.fetchone() or [0])[0] or 0)
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM companies c
                    LEFT JOIN company_subscriptions s ON s.company_id = c.id
                    WHERE s.company_id IS NULL
                    """
                )
                out["without_subscription"] = int((cur.fetchone() or [0])[0] or 0)
    except Exception:
        logger.exception("get_company_subscription_metrics_max failed")
    return out


def list_expiring_company_subscriptions_max(days: int = 7, limit: int = 30) -> list[dict[str, Any]]:
    if not DATABASE_URL:
        return []
    d = max(1, min(90, int(days or 7)))
    lim = max(1, min(200, int(limit or 30)))
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT c.id,
                           COALESCE(c.name, '') AS company_name,
                           COALESCE(s.plan_code, 'legacy') AS plan_code,
                           COALESCE(s.status, 'active') AS status,
                           s.projects_limit,
                           s.ends_at,
                           COUNT(p.id)::int AS projects_used
                    FROM company_subscriptions s
                    JOIN companies c ON c.id = s.company_id
                    LEFT JOIN projects p ON p.company_id = c.id
                    WHERE s.ends_at IS NOT NULL
                      AND s.ends_at > NOW()
                      AND s.ends_at <= (NOW() + (%s || ' days')::interval)
                    GROUP BY c.id, c.name, s.plan_code, s.status, s.projects_limit, s.ends_at
                    ORDER BY s.ends_at ASC, c.id ASC
                    LIMIT %s
                    """,
                    (d, lim),
                )
                rows = cur.fetchall() or []
    except Exception:
        logger.exception("list_expiring_company_subscriptions_max failed")
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "company_id": int(row[0]),
                "company_name": str(row[1] or ""),
                "plan_code": str(row[2] or "legacy"),
                "status": str(row[3] or "active"),
                "projects_limit": int(row[4]) if row[4] is not None else None,
                "ends_at": row[5],
                "projects_used": int(row[6] or 0),
            }
        )
    return out


def list_expired_company_subscriptions_max(limit: int = 30) -> list[dict[str, Any]]:
    if not DATABASE_URL:
        return []
    lim = max(1, min(200, int(limit or 30)))
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT c.id,
                           COALESCE(c.name, '') AS company_name,
                           COALESCE(s.plan_code, 'legacy') AS plan_code,
                           COALESCE(s.status, 'active') AS status,
                           s.projects_limit,
                           s.ends_at,
                           COUNT(p.id)::int AS projects_used
                    FROM company_subscriptions s
                    JOIN companies c ON c.id = s.company_id
                    LEFT JOIN projects p ON p.company_id = c.id
                    WHERE s.ends_at IS NOT NULL
                      AND s.ends_at <= NOW()
                    GROUP BY c.id, c.name, s.plan_code, s.status, s.projects_limit, s.ends_at
                    ORDER BY s.ends_at DESC, c.id ASC
                    LIMIT %s
                    """,
                    (lim,),
                )
                rows = cur.fetchall() or []
    except Exception:
        logger.exception("list_expired_company_subscriptions_max failed")
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "company_id": int(row[0]),
                "company_name": str(row[1] or ""),
                "plan_code": str(row[2] or "legacy"),
                "status": str(row[3] or "active"),
                "projects_limit": int(row[4]) if row[4] is not None else None,
                "ends_at": row[5],
                "projects_used": int(row[6] or 0),
            }
        )
    return out


def get_company_subscription_max(company_id: int) -> dict[str, Any] | None:
    if not DATABASE_URL:
        return None
    cid = int(company_id)
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT company_id, plan_code, status, projects_limit, starts_at, ends_at, auto_renew, notes
                    FROM company_subscriptions
                    WHERE company_id = %s
                    LIMIT 1
                    """,
                    (cid,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "company_id": int(row[0]),
                    "plan_code": str(row[1] or "legacy"),
                    "status": str(row[2] or "active"),
                    "projects_limit": int(row[3]) if row[3] is not None else None,
                    "starts_at": row[4],
                    "ends_at": row[5],
                    "auto_renew": bool(row[6]),
                    "notes": str(row[7] or ""),
                }
    except Exception:
        logger.exception("get_company_subscription_max failed company_id=%s", cid)
        return None


def count_projects_for_company_max(company_id: int) -> int:
    if not DATABASE_URL:
        return 0
    cid = int(company_id)
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM projects WHERE company_id = %s", (cid,))
                return int((cur.fetchone() or [0])[0] or 0)
    except Exception:
        logger.exception("count_projects_for_company_max failed company_id=%s", cid)
        return 0


def get_client_company_id_max(max_user_id: int) -> int | None:
    if not DATABASE_URL:
        return None
    uid = int(max_user_id)
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                tg_id = resolve_tg_id_for_max_user(uid)
                cur.execute(
                    """
                    SELECT company_id
                    FROM users
                    WHERE company_id IS NOT NULL
                      AND (
                        max_user_id = %s
                        OR tg_id = %s
                        OR tg_id = %s
                      )
                    ORDER BY updated_at DESC NULLS LAST, tg_id DESC
                    LIMIT 1
                    """,
                    (uid, tg_id, worker_tg_id_for_max(uid)),
                )
                row = cur.fetchone()
                if row and row[0]:
                    return int(row[0])
    except Exception:
        logger.exception("get_client_company_id_max users lookup failed max_uid=%s", uid)
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT company_id
                    FROM agency_max_visit_clients
                    WHERE max_user_id = %s AND company_id IS NOT NULL
                    LIMIT 1
                    """,
                    (uid,),
                )
                row = cur.fetchone()
                if row and row[0]:
                    return int(row[0])
    except Exception:
        logger.exception("get_client_company_id_max max_visit_clients lookup failed max_uid=%s", uid)
    return None


def list_projects_for_company_max(company_id: int, limit: int = 40) -> list[dict[str, Any]]:
    if not DATABASE_URL:
        return []
    cid = int(company_id)
    lim = max(1, min(200, int(limit or 40)))
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        p.id,
                        COALESCE(p.name, ''),
                        COALESCE(p.status, ''),
                        p.start_date,
                        p.end_date,
                        COALESCE(p.budget, 0),
                        COUNT(s.id)::int AS shifts_count
                    FROM projects p
                    LEFT JOIN shifts s ON s.project_id = p.id
                    WHERE p.company_id = %s
                    GROUP BY p.id, p.name, p.status, p.start_date, p.end_date, p.budget
                    ORDER BY p.id DESC
                    LIMIT %s
                    """,
                    (cid, lim),
                )
                rows = cur.fetchall() or []
    except Exception:
        logger.exception("list_projects_for_company_max failed company_id=%s", cid)
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": int(r[0]),
                "name": str(r[1] or ""),
                "status": str(r[2] or ""),
                "start_date": str(r[3] or ""),
                "end_date": str(r[4] or ""),
                "budget": float(r[5] or 0),
                "shifts_count": int(r[6] or 0),
            }
        )
    return out


def get_company_project_quota_status_max(company_id: int) -> dict[str, Any]:
    cid = int(company_id)
    sub = get_company_subscription_max(cid)
    used = count_projects_for_company_max(cid)
    active_statuses = {"active", "trial", "grace"}
    if not sub:
        return {
            "company_id": cid,
            "has_subscription": False,
            "plan_code": "legacy",
            "status": "active",
            "is_subscription_active": True,
            "projects_limit": None,
            "projects_used": used,
            "projects_left": None,
            "can_create_project": True,
            "ends_at": None,
        }
    status = str(sub.get("status") or "active").strip().lower()
    ends_at = sub.get("ends_at")
    is_active = status in active_statuses
    if is_active and ends_at is not None:
        try:
            is_active = bool(ends_at > datetime.now())
        except Exception:
            is_active = True
    limit = sub.get("projects_limit")
    left = None if limit is None else max(0, int(limit) - used)
    can_create = bool(is_active) and (limit is None or used < int(limit))
    return {
        "company_id": cid,
        "has_subscription": True,
        "plan_code": str(sub.get("plan_code") or "legacy"),
        "status": status,
        "is_subscription_active": bool(is_active),
        "projects_limit": int(limit) if limit is not None else None,
        "projects_used": used,
        "projects_left": left,
        "can_create_project": can_create,
        "ends_at": ends_at,
    }


def require_company_can_create_project_max(company_id: int) -> None:
    q = get_company_project_quota_status_max(int(company_id))
    if q.get("can_create_project"):
        return
    if not q.get("is_subscription_active"):
        raise ValueError("Подписка компании не активна. Продлите тариф и повторите создание проекта.")
    limit = q.get("projects_limit")
    used = int(q.get("projects_used") or 0)
    raise ValueError(
        f"Достигнут лимит проектов по подписке: {used}/{int(limit)}. Закройте проект или увеличьте лимит."
    )


def create_project_for_company_max(company_id: int, name: str) -> int:
    if not DATABASE_URL:
        raise ValueError("База данных недоступна")
    cid = int(company_id)
    project_name = (name or "").strip()
    if not project_name:
        raise ValueError("Название проекта не заполнено.")
    require_company_can_create_project_max(cid)
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO projects (name, company_id, start_date, end_date, status, created_at)
                VALUES (%s, %s, NOW(), NOW() + INTERVAL '30 days', 'planned', NOW())
                RETURNING id
                """,
                (project_name, cid),
            )
            row = cur.fetchone()
            if not row:
                raise RuntimeError("Не удалось получить ID проекта")
            return int(row[0])


def list_company_team_for_client_max(company_id: int, limit: int = 40) -> list[dict[str, Any]]:
    if not DATABASE_URL:
        return []
    cid = int(company_id)
    lim = max(1, min(120, int(limit or 40)))
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        w.tg_id,
                        COALESCE(w.full_name, ''),
                        COALESCE(w.profession, ''),
                        COALESCE(w.rating, 0),
                        COUNT(sa.id)::int AS shifts_count
                    FROM workers w
                    JOIN shift_assignments sa ON sa.worker_tg_id = w.tg_id
                    JOIN shifts s ON s.id = sa.shift_id
                    JOIN projects p ON p.id = s.project_id
                    WHERE p.company_id = %s
                    GROUP BY w.tg_id, w.full_name, w.profession, w.rating
                    ORDER BY shifts_count DESC, w.tg_id DESC
                    LIMIT %s
                    """,
                    (cid, lim),
                )
                rows = cur.fetchall() or []
    except Exception:
        logger.exception("list_company_team_for_client_max failed company_id=%s", cid)
        return []
    return [
        {
            "worker_tg_id": int(r[0]),
            "full_name": str(r[1] or ""),
            "profession": str(r[2] or ""),
            "rating": float(r[3] or 0),
            "shifts_count": int(r[4] or 0),
        }
        for r in rows
    ]


def _upsert_company_subscription_max(
    company_id: int,
    *,
    plan_code: str,
    status: str,
    projects_limit: int | None,
    starts_at: Any,
    ends_at: Any,
    auto_renew: bool,
    notes: str,
) -> bool:
    cid = int(company_id)
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO company_subscriptions (
                        company_id, plan_code, status, projects_limit, starts_at, ends_at,
                        auto_renew, notes, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                    ON CONFLICT (company_id) DO UPDATE SET
                        plan_code = EXCLUDED.plan_code,
                        status = EXCLUDED.status,
                        projects_limit = EXCLUDED.projects_limit,
                        starts_at = EXCLUDED.starts_at,
                        ends_at = EXCLUDED.ends_at,
                        auto_renew = EXCLUDED.auto_renew,
                        notes = EXCLUDED.notes,
                        updated_at = NOW()
                    """,
                    (
                        cid,
                        (plan_code or "manual").strip() or "manual",
                        (status or "active").strip().lower() or "active",
                        int(projects_limit) if projects_limit is not None else None,
                        starts_at,
                        ends_at,
                        bool(auto_renew),
                        (notes or "").strip(),
                    ),
                )
        return True
    except Exception:
        logger.exception("_upsert_company_subscription_max failed company_id=%s", cid)
        return False


def admin_extend_company_subscription_days_max(company_id: int, days: int = 30) -> bool:
    if not DATABASE_URL:
        return False
    cid = int(company_id)
    dd = max(1, min(3650, int(days or 30)))
    sub = get_company_subscription_max(cid) or {}
    ends_at = sub.get("ends_at")
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM companies WHERE id = %s", (cid,))
                if not cur.fetchone():
                    return False
    except Exception:
        logger.exception("admin_extend_company_subscription_days_max company check failed company_id=%s", cid)
        return False
    from datetime import datetime, timedelta

    now = datetime.now()
    base = now
    if ends_at is not None:
        try:
            base = ends_at if ends_at > now else now
        except Exception:
            base = now
    return _upsert_company_subscription_max(
        cid,
        plan_code=str(sub.get("plan_code") or "manual"),
        status="active",
        projects_limit=int(sub.get("projects_limit")) if sub.get("projects_limit") is not None else None,
        starts_at=sub.get("starts_at") or now,
        ends_at=base + timedelta(days=dd),
        auto_renew=bool(sub.get("auto_renew")),
        notes=str(sub.get("notes") or "admin_extend"),
    )


def admin_set_company_subscription_grace_max(company_id: int, days: int = 7) -> bool:
    if not DATABASE_URL:
        return False
    cid = int(company_id)
    dd = max(1, min(365, int(days or 7)))
    sub = get_company_subscription_max(cid) or {}
    ends_at = sub.get("ends_at")
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM companies WHERE id = %s", (cid,))
                if not cur.fetchone():
                    return False
    except Exception:
        logger.exception("admin_set_company_subscription_grace_max company check failed company_id=%s", cid)
        return False
    from datetime import datetime, timedelta

    now = datetime.now()
    base = now
    if ends_at is not None:
        try:
            base = ends_at if ends_at > now else now
        except Exception:
            base = now
    return _upsert_company_subscription_max(
        cid,
        plan_code=str(sub.get("plan_code") or "manual"),
        status="grace",
        projects_limit=int(sub.get("projects_limit")) if sub.get("projects_limit") is not None else None,
        starts_at=sub.get("starts_at") or now,
        ends_at=base + timedelta(days=dd),
        auto_renew=bool(sub.get("auto_renew")),
        notes=str(sub.get("notes") or "admin_grace"),
    )


# --- vacancy_campaigns (паритет promostaff-agency-bot/db.py) ---


def _vacancy_campaign_tuple_to_dict(row: tuple) -> dict | None:
    if not row or len(row) < 15:
        return None
    return {
        "id": int(row[0]),
        "admin_tg_id": int(row[1]),
        "position": str(row[2] or ""),
        "city": str(row[3] or ""),
        "address": str(row[4] or ""),
        "shift_date": str(row[5] or ""),
        "shift_time": str(row[6] or ""),
        "pay": str(row[7] or ""),
        "tasks": str(row[8] or ""),
        "min_rating": float(row[9] or 0.0),
        "slots_needed": int(row[10] or 0),
        "status": str(row[11] or "open"),
        "payload": str(row[12] or ""),
        "created_at": row[13],
        "updated_at": row[14],
    }


def get_worker_row_for_tg(tg_user_id: int) -> dict[str, Any] | None:
    if not DATABASE_URL:
        return None
    uid = int(tg_user_id)
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT full_name, phone, profession, status, rating
                    FROM workers WHERE user_id = %s LIMIT 1
                    """,
                    (uid,),
                )
                row = cur.fetchone()
    except Exception:
        logger.exception("get_worker_row_for_tg uid=%s", uid)
        return None
    if not row:
        return None
    return {
        "full_name": row[0],
        "phone": row[1],
        "profession": row[2],
        "status": row[3],
        "rating": row[4],
    }


def get_vacancy_campaign(campaign_id: int) -> dict | None:
    if not DATABASE_URL:
        return None
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, admin_tg_id, position, city, address, shift_date, shift_time,
                           pay, tasks, min_rating, slots_needed, status, payload,
                           created_at, updated_at
                    FROM vacancy_campaigns WHERE id = %s
                    """,
                    (int(campaign_id),),
                )
                row = cur.fetchone()
    except Exception:
        logger.exception("get_vacancy_campaign id=%s", campaign_id)
        return None
    return _vacancy_campaign_tuple_to_dict(row) if row else None


def list_open_vacancy_campaigns(limit: int = 30) -> list[dict]:
    if not DATABASE_URL:
        return []
    lim = max(1, min(int(limit), 100))
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT c.id, c.admin_tg_id, c.position, c.city, c.address, c.shift_date, c.shift_time,
                           c.pay, c.tasks, c.min_rating, c.slots_needed, c.status, c.payload,
                           c.created_at, c.updated_at,
                           (SELECT COUNT(*)::int FROM vacancy_campaign_responses r WHERE r.campaign_id = c.id) AS response_count
                    FROM vacancy_campaigns c
                    WHERE c.status = 'open'
                    ORDER BY c.created_at DESC NULLS LAST, c.id DESC
                    LIMIT %s
                    """,
                    (lim,),
                )
                rows = cur.fetchall() or []
    except Exception:
        logger.exception("list_open_vacancy_campaigns")
        return []
    out: list[dict] = []
    for row in rows:
        base = _vacancy_campaign_tuple_to_dict(row[:15])
        if base:
            base["response_count"] = int(row[15] or 0)
            out.append(base)
    return out


def list_user_vacancy_responses_current(tg_user_id: int, limit: int = 40) -> list[dict]:
    if not DATABASE_URL:
        return []
    lim = max(1, min(int(limit), 80))
    uid = int(tg_user_id)
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT c.id, c.admin_tg_id, c.position, c.city, c.address, c.shift_date, c.shift_time,
                           c.pay, c.tasks, c.min_rating, c.slots_needed, c.status, c.payload,
                           c.created_at, c.updated_at,
                           r.created_at AS responded_at,
                           (SELECT COUNT(*)::int FROM vacancy_campaign_responses r2 WHERE r2.campaign_id = c.id) AS response_count
                    FROM vacancy_campaign_responses r
                    INNER JOIN vacancy_campaigns c ON c.id = r.campaign_id
                    WHERE r.user_id = %s AND c.status IN ('open', 'filled')
                    ORDER BY r.created_at DESC NULLS LAST, r.id DESC
                    LIMIT %s
                    """,
                    (uid, lim),
                )
                rows = cur.fetchall() or []
    except Exception:
        logger.exception("list_user_vacancy_responses_current uid=%s", uid)
        return []
    out: list[dict] = []
    for row in rows:
        base = _vacancy_campaign_tuple_to_dict(row[:15])
        if base:
            base["responded_at"] = row[15]
            base["response_count"] = int(row[16] or 0)
            out.append(base)
    return out


def list_user_vacancy_responses_past(tg_user_id: int, limit: int = 40) -> list[dict]:
    if not DATABASE_URL:
        return []
    lim = max(1, min(int(limit), 80))
    uid = int(tg_user_id)
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT c.id, c.admin_tg_id, c.position, c.city, c.address, c.shift_date, c.shift_time,
                           c.pay, c.tasks, c.min_rating, c.slots_needed, c.status, c.payload,
                           c.created_at, c.updated_at,
                           r.created_at AS responded_at,
                           (SELECT COUNT(*)::int FROM vacancy_campaign_responses r2 WHERE r2.campaign_id = c.id) AS response_count
                    FROM vacancy_campaign_responses r
                    INNER JOIN vacancy_campaigns c ON c.id = r.campaign_id
                    WHERE r.user_id = %s AND c.status = 'closed'
                    ORDER BY r.created_at DESC NULLS LAST, r.id DESC
                    LIMIT %s
                    """,
                    (uid, lim),
                )
                rows = cur.fetchall() or []
    except Exception:
        logger.exception("list_user_vacancy_responses_past uid=%s", uid)
        return []
    out: list[dict] = []
    for row in rows:
        base = _vacancy_campaign_tuple_to_dict(row[:15])
        if base:
            base["responded_at"] = row[15]
            base["response_count"] = int(row[16] or 0)
            out.append(base)
    return out


def vacancy_campaign_response_count(campaign_id: int) -> int:
    if not DATABASE_URL:
        return 0
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM vacancy_campaign_responses WHERE campaign_id = %s",
                    (int(campaign_id),),
                )
                row = cur.fetchone()
    except Exception:
        logger.exception("vacancy_campaign_response_count id=%s", campaign_id)
        return 0
    return int(row[0] or 0) if row else 0


def vacancy_campaign_set_status(campaign_id: int, status: str) -> None:
    if not DATABASE_URL:
        return
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE vacancy_campaigns SET status = %s, updated_at = NOW() WHERE id = %s",
                    (str(status), int(campaign_id)),
                )
            conn.commit()
    except Exception:
        logger.exception("vacancy_campaign_set_status id=%s", campaign_id)


def vacancy_campaign_add_response(campaign_id: int, tg_user_id: int) -> dict:
    if not DATABASE_URL:
        return {"ok": False, "reason": "no_pg"}
    camp = get_vacancy_campaign(campaign_id)
    if not camp:
        return {"ok": False, "reason": "not_found"}
    if camp["status"] != "open":
        return {"ok": False, "reason": "closed", "status": camp["status"]}
    try:
        from max_vacancy_rules import vacancy_rating_gate_for_response

        gate = vacancy_rating_gate_for_response(int(tg_user_id), camp)
        if not gate.get("allowed"):
            return {
                "ok": False,
                "reason": "rating",
                "min_rating": float(gate.get("min_rating") or 0.0),
                "effective": float(gate.get("effective") or 0.0),
            }
    except Exception:
        logger.exception("vacancy_campaign_add_response gate uid=%s cid=%s", tg_user_id, campaign_id)
    needed = int(camp["slots_needed"] or 0)
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO vacancy_campaign_responses (campaign_id, user_id)
                    VALUES (%s, %s)
                    ON CONFLICT (campaign_id, user_id) DO NOTHING
                    RETURNING id
                    """,
                    (int(campaign_id), int(tg_user_id)),
                )
                new = cur.fetchone() is not None
            conn.commit()
    except Exception:
        logger.exception("vacancy_campaign_add_response insert uid=%s cid=%s", tg_user_id, campaign_id)
        return {"ok": False, "reason": "db"}
    cnt = vacancy_campaign_response_count(campaign_id)
    filled = needed > 0 and cnt >= needed
    if filled:
        vacancy_campaign_set_status(campaign_id, "filled")
    return {"ok": True, "new": new, "count": cnt, "needed": needed, "filled": filled}


def _max_client_verified(max_uid: int) -> bool:
    return is_max_visit_client_verified(max_uid)


def list_company_members_max(
    company_id: int,
    *,
    member_role: str,
    limit: int = 10,
    offset: int = 0,
) -> list[dict[str, Any]]:
    if not DATABASE_URL:
        return []
    role = (member_role or "staff").strip().lower()
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT cm.tg_id, COALESCE(u.full_name, ''), COALESCE(u.phone, ''),
                           COALESCE(w.profession, ''), COALESCE(cm.verification_status, ''),
                           COALESCE(w.status, '')
                    FROM company_members cm
                    LEFT JOIN users u ON u.tg_id = cm.tg_id
                    LEFT JOIN workers w ON w.user_id = cm.tg_id
                    WHERE cm.company_id = %s AND cm.member_role = %s
                    ORDER BY cm.created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (int(company_id), role, max(1, min(limit, 50)), max(0, offset)),
                )
                rows = cur.fetchall() or []
    except Exception:
        logger.exception("list_company_members_max company_id=%s", company_id)
        return []
    return [
        {
            "tg_id": int(r[0]),
            "full_name": str(r[1] or ""),
            "phone": str(r[2] or ""),
            "profession": str(r[3] or ""),
            "verification_status": str(r[4] or ""),
            "worker_status": str(r[5] or ""),
        }
        for r in rows
        if int(r[0] or 0) > 0
    ]


def count_company_members_max(company_id: int, *, member_role: str) -> int:
    if not DATABASE_URL:
        return 0
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM company_members WHERE company_id = %s AND member_role = %s",
                    (int(company_id), (member_role or "staff").strip().lower()),
                )
                row = cur.fetchone()
                return int(row[0] if row else 0)
    except Exception:
        return 0


def create_company_invite_max(
    *,
    company_id: int,
    invite_kind: str,
    created_by_max_uid: int | None,
    ttl_days: int = 14,
    project_id: int | None = None,
) -> str:
    import secrets

    if not DATABASE_URL:
        return secrets.token_hex(16)
    created_by_tg = resolve_tg_id_for_max_user(int(created_by_max_uid)) if created_by_max_uid else None
    token = secrets.token_hex(16)
    kind = (invite_kind or "staff").strip().lower()[:32]
    ttl = max(1, min(int(ttl_days or 14), 90))
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO company_invites (
                        token, company_id, project_id, invite_kind, created_by_tg_id, expires_at
                    )
                    VALUES (%s, %s, %s, %s, %s, NOW() + (%s::int * INTERVAL '1 day'))
                    """,
                    (token, int(company_id), project_id, kind, created_by_tg, ttl),
                )
            conn.commit()
    except Exception:
        logger.exception("create_company_invite_max company_id=%s", company_id)
        return token
    return token


def list_shifts_for_company_max(company_id: int, *, limit: int = 8, offset: int = 0) -> tuple[list[dict], int]:
    if not DATABASE_URL:
        return [], 0
    lim, off = max(1, min(int(limit), 30)), max(0, int(offset))
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) FROM shifts s
                    JOIN projects p ON s.project_id = p.id WHERE p.company_id = %s
                    """,
                    (int(company_id),),
                )
                total = int((cur.fetchone() or [0])[0] or 0)
                cur.execute(
                    """
                    SELECT s.id, s.shift_date, s.start_time, s.end_time, p.name
                    FROM shifts s JOIN projects p ON s.project_id = p.id
                    WHERE p.company_id = %s
                    ORDER BY s.shift_date DESC, s.id DESC
                    LIMIT %s OFFSET %s
                    """,
                    (int(company_id), lim, off),
                )
                rows = cur.fetchall() or []
    except Exception:
        logger.exception("list_shifts_for_company_max")
        return [], 0
    out = [
        {
            "id": int(r[0]),
            "shift_date": r[1],
            "start_time": r[2],
            "end_time": r[3],
            "project_name": str(r[4] or ""),
        }
        for r in rows
    ]
    return out, total


def list_client_pool_assignable_max(
    company_id: int,
    shift_id: int,
    *,
    limit: int = 8,
    offset: int = 0,
) -> tuple[list[dict], int]:
    if not DATABASE_URL:
        return [], 0
    lim, off = max(1, min(int(limit), 30)), max(0, int(offset))
    sid = int(shift_id)
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM company_members cm
                    JOIN workers w ON w.user_id = cm.tg_id
                    WHERE cm.company_id = %s AND cm.member_role = 'staff'
                      AND LOWER(COALESCE(cm.verification_status, '')) = %s
                      AND LOWER(COALESCE(w.status, '')) = %s
                      AND NOT EXISTS (
                        SELECT 1 FROM shift_assignments sa
                        WHERE sa.shift_id = %s AND sa.worker_tg_id = cm.tg_id
                      )
                    """,
                    (int(company_id), COMPANY_MEMBER_VER_APPROVED, WORKER_STATUS_APPROVED, sid),
                )
                total = int((cur.fetchone() or [0])[0] or 0)
                cur.execute(
                    """
                    SELECT cm.tg_id, COALESCE(u.full_name, w.full_name, ''), COALESCE(w.profession, '')
                    FROM company_members cm
                    JOIN workers w ON w.user_id = cm.tg_id
                    LEFT JOIN users u ON u.tg_id = cm.tg_id
                    WHERE cm.company_id = %s AND cm.member_role = 'staff'
                      AND LOWER(COALESCE(cm.verification_status, '')) = %s
                      AND LOWER(COALESCE(w.status, '')) = %s
                      AND NOT EXISTS (
                        SELECT 1 FROM shift_assignments sa
                        WHERE sa.shift_id = %s AND sa.worker_tg_id = cm.tg_id
                      )
                    ORDER BY cm.created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (
                        int(company_id),
                        COMPANY_MEMBER_VER_APPROVED,
                        WORKER_STATUS_APPROVED,
                        sid,
                        lim,
                        off,
                    ),
                )
                rows = cur.fetchall() or []
    except Exception:
        logger.exception("list_client_pool_assignable_max")
        return [], 0
    return [
        {"tg_id": int(r[0]), "full_name": str(r[1] or ""), "profession": str(r[2] or "")}
        for r in rows
        if int(r[0] or 0) > 0
    ], total


def assign_worker_client_pool_max(shift_id: int, worker_tg_id: int, company_id: int) -> tuple[bool, str]:
    if not DATABASE_URL:
        return False, "Нужен PostgreSQL."
    sid, wid, cid = int(shift_id), int(worker_tg_id), int(company_id)
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM shifts s
                    JOIN projects p ON s.project_id = p.id
                    WHERE s.id = %s AND p.company_id = %s
                    """,
                    (sid, cid),
                )
                if not cur.fetchone():
                    return False, "Нет доступа к смене."
                cur.execute(
                    """
                    SELECT 1 FROM company_members cm
                    JOIN workers w ON w.user_id = cm.tg_id
                    WHERE cm.company_id = %s AND cm.tg_id = %s AND cm.member_role = 'staff'
                      AND LOWER(COALESCE(cm.verification_status, '')) = %s
                      AND LOWER(COALESCE(w.status, '')) = %s
                    """,
                    (cid, wid, COMPANY_MEMBER_VER_APPROVED, WORKER_STATUS_APPROVED),
                )
                if not cur.fetchone():
                    return False, "Исполнитель не в команде или не верифицирован."
                cur.execute(
                    """
                    INSERT INTO shift_assignments (shift_id, worker_tg_id, status, created_at)
                    VALUES (%s, %s, 'assigned', NOW())
                    ON CONFLICT (shift_id, worker_tg_id) DO NOTHING
                    """,
                    (sid, wid),
                )
                if int(cur.rowcount or 0) <= 0:
                    return False, "Уже назначен."
            conn.commit()
        return True, "Исполнитель назначен."
    except Exception:
        logger.exception("assign_worker_client_pool_max")
        return False, "Ошибка БД."


def create_shift_for_company_max(project_id: int, data: dict[str, Any]) -> int:
    if not DATABASE_URL:
        raise RuntimeError("Нужен PostgreSQL.")
    raw_date = str(data.get("date") or "").strip()
    date_iso = raw_date
    try:
        from visit_join_validators import normalize_shift_date

        date_iso = normalize_shift_date(raw_date)
    except Exception:
        from datetime import datetime as dt_cls

        for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
            try:
                date_iso = dt_cls.strptime(raw_date, fmt).strftime("%Y-%m-%d")
                break
            except ValueError:
                continue
    pid = int(project_id)
    rate = int(data.get("rate") or 500)
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO shifts (
                        project_id, shift_date, start_time, end_time, location, rate,
                        workers_needed, status, created_at
                    )
                    VALUES (%s, %s::date, %s, %s, %s, %s, 1, 'open', NOW())
                    RETURNING id
                    """,
                    (
                        pid,
                        date_iso,
                        data.get("start_time"),
                        data.get("end_time"),
                        data.get("location"),
                        rate,
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        return int(row[0]) if row else 0
    except Exception:
        logger.exception("create_shift_for_company_max project_id=%s", project_id)
        raise


def client_owns_shift_max(company_id: int, shift_id: int) -> bool:
    if not DATABASE_URL:
        return False
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM shifts s JOIN projects p ON s.project_id = p.id
                    WHERE s.id = %s AND p.company_id = %s
                    """,
                    (int(shift_id), int(company_id)),
                )
                return cur.fetchone() is not None
    except Exception:
        return False
