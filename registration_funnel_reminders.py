"""
Напоминания о незавершённых сценариях визитки MAX (расчёт / вопрос / анкета).

Логика как в PROMOSTAFF PRO (Telegram): 24 ч без активности на шаге; второе через 72 ч
только если уже был телефон на шаге (заказ или анкета). Доставка — Platform API MAX.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import psycopg2

from config import COMPANY_NAME, DATABASE_URL, MAX_TOKEN
from max_client import post_message

logger = logging.getLogger(__name__)


def _utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


MSG_24H = (
    f"Вы начали оформление заявки в боте {COMPANY_NAME}, но не завершили его.\n\n"
    "Продолжите в любое время: откройте этот чат с ботом — мы подхватим с того же шага."
)

MSG_72H_WARM = (
    f"Напоминаем: заявка в {COMPANY_NAME} всё ещё не отправлена.\n\n"
    "Напишите боту «меню» или нажмите /start и продолжите с нужного раздела."
)


def _run(cur, sql: str, params: tuple | None = None) -> None:
    cur.execute(sql, params or ())


def fetch_users_for_24h_reminder() -> list[int]:
    if not DATABASE_URL:
        return []
    from funnel_db import connection

    with connection() as conn:
        with conn.cursor() as cur:
            _run(
                cur,
                """
                SELECT max_user_id FROM agency_max_funnel
                WHERE funnel_completed_at IS NULL
                  AND state IS NOT NULL
                  AND (state LIKE 'reg\\_%' ESCAPE '\\' OR state LIKE 'waiting%%')
                  AND funnel_last_step_at IS NOT NULL
                  AND funnel_last_step_at < NOW() - INTERVAL '24 hours'
                  AND funnel_reminder_24h_sent_at IS NULL
                """,
            )
            rows = cur.fetchall() or []
            return [int(r[0]) for r in rows]


def fetch_users_for_72h_reminder() -> list[int]:
    if not DATABASE_URL:
        return []
    from funnel_db import connection

    with connection() as conn:
        with conn.cursor() as cur:
            _run(
                cur,
                """
                SELECT max_user_id FROM agency_max_funnel
                WHERE funnel_completed_at IS NULL
                  AND state IS NOT NULL
                  AND (state LIKE 'reg\\_%' ESCAPE '\\' OR state LIKE 'waiting%%')
                  AND funnel_phone_reached_at IS NOT NULL
                  AND funnel_reminder_24h_sent_at IS NOT NULL
                  AND funnel_reminder_72h_sent_at IS NULL
                  AND funnel_last_step_at IS NOT NULL
                  AND funnel_last_step_at < NOW() - INTERVAL '72 hours'
                """,
            )
            rows = cur.fetchall() or []
            return [int(r[0]) for r in rows]


def mark_reminder_24h_sent(max_user_id: int) -> None:
    if not DATABASE_URL:
        return
    from funnel_db import connection

    now = _utc_naive()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE agency_max_funnel SET funnel_reminder_24h_sent_at = %s, updated_at = NOW()
                WHERE max_user_id = %s AND funnel_reminder_24h_sent_at IS NULL
                """,
                (now, max_user_id),
            )


def mark_reminder_72h_sent(max_user_id: int) -> None:
    if not DATABASE_URL:
        return
    from funnel_db import connection

    now = _utc_naive()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE agency_max_funnel SET funnel_reminder_72h_sent_at = %s, updated_at = NOW()
                WHERE max_user_id = %s AND funnel_reminder_72h_sent_at IS NULL
                """,
                (now, max_user_id),
            )


async def process_agency_funnel_reminders() -> None:
    """Один проход: 24h, затем 72h warm."""
    if not MAX_TOKEN or not DATABASE_URL:
        return

    body_24 = {"text": MSG_24H, "format": "markdown"}
    body_72 = {"text": MSG_72H_WARM, "format": "markdown"}

    try:
        for uid in fetch_users_for_24h_reminder():
            try:
                ok = await post_message(MAX_TOKEN, uid, body_24)
                if ok:
                    mark_reminder_24h_sent(uid)
            except Exception as e:
                logger.warning("reminder 24h failed max_user_id=%s: %s", uid, e)
    except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
        logger.warning("reminder 24h db: %s", e)

    try:
        for uid in fetch_users_for_72h_reminder():
            try:
                ok = await post_message(MAX_TOKEN, uid, body_72)
                if ok:
                    mark_reminder_72h_sent(uid)
            except Exception as e:
                logger.warning("reminder 72h failed max_user_id=%s: %s", uid, e)
    except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
        logger.warning("reminder 72h db: %s", e)
