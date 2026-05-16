"""Уточнения по анкете исполнителя (общая БД с Telegram-ботом)."""
from __future__ import annotations

import json
import logging
from typing import Any

from funnel_db import (
    WORKER_STATUS_CLARIFICATION,
    WORKER_STATUS_PENDING_REVIEW,
    _HRM_PIPELINE,
    _HRM_JOIN_SOURCE,
    _sync_hrm_crm_card_for_join_request,
    connection,
    worker_tg_id_for_max,
)

logger = logging.getLogger(__name__)

CLARIFICATION_FLAG_LABELS_RU: dict[str, str] = {
    "pm": "фото паспорта (главный разворот)",
    "pr": "фото прописки",
    "ps": "серия и номер паспорта",
    "tx": "ИНН",
    "sf": "селфи",
    "fn": "ФИО",
    "ph": "телефон",
    "mb": "медкнижка",
}
VALID_CLARIFICATION_FLAG_CODES = frozenset(CLARIFICATION_FLAG_LABELS_RU.keys())


def _json_loads(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if raw is None:
        return {}
    try:
        return json.loads(raw) if isinstance(raw, str) else {}
    except Exception:
        return {}


def _nonempty(val: object) -> bool:
    return bool(str(val or "").strip())


def _flag_satisfied(code: str, pl: dict[str, Any]) -> bool:
    if code == "pm":
        return _nonempty(pl.get("passport_main_file_id")) or _nonempty(pl.get("passport_main_ref"))
    if code == "pr":
        return _nonempty(pl.get("passport_reg_file_id")) or _nonempty(pl.get("passport_reg_ref"))
    if code == "ps":
        return _nonempty(pl.get("passport_sn"))
    if code == "tx":
        return _nonempty(pl.get("tax_inn"))
    if code == "sf":
        return _nonempty(pl.get("selfie_url")) or _nonempty(pl.get("selfie_ref"))
    if code == "fn":
        return _nonempty(pl.get("full_name"))
    if code == "ph":
        return _nonempty(pl.get("phone"))
    if code == "mb":
        return _nonempty(pl.get("medbook_number")) or _nonempty(pl.get("medbook_expiry"))
    return False


def get_max_worker_status(max_user_id: int) -> str:
    tg = worker_tg_id_for_max(int(max_user_id))
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COALESCE(status, 'new') FROM workers WHERE user_id = %s LIMIT 1",
                    (tg,),
                )
                row = cur.fetchone()
                return str(row[0] or "new").strip().lower() if row else ""
    except Exception:
        logger.exception("get_max_worker_status")
    return ""


def get_max_join_clarification_context(max_user_id: int) -> dict[str, Any]:
    """Флаги и комментарий из последней заявки, если статус clarification_needed."""
    tg = worker_tg_id_for_max(int(max_user_id))
    st = get_max_worker_status(max_user_id)
    if st != WORKER_STATUS_CLARIFICATION:
        return {"status": st, "flags": [], "note": ""}
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload FROM agency_visit_join_requests
                    WHERE user_id = %s ORDER BY id DESC LIMIT 1
                    """,
                    (tg,),
                )
                row = cur.fetchone()
        pl = _json_loads(row[0]) if row else {}
        flags = pl.get("clarification_flags") if isinstance(pl.get("clarification_flags"), list) else []
        flags = [str(x).strip().lower() for x in flags if str(x).strip().lower() in VALID_CLARIFICATION_FLAG_CODES]
        note = str(pl.get("clarification_note") or "").strip()
        return {"status": st, "flags": flags, "note": note}
    except Exception:
        logger.exception("get_max_join_clarification_context")
        return {"status": st, "flags": [], "note": ""}


def apply_join_clarification_patch(max_user_id: int, patch: dict[str, Any]) -> dict[str, Any] | None:
    tg = worker_tg_id_for_max(int(max_user_id))
    patch = dict(patch or {})
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COALESCE(status, '') FROM workers WHERE user_id = %s LIMIT 1",
                    (tg,),
                )
                wrow = cur.fetchone()
                if not wrow:
                    return None
                if str(wrow[0] or "").strip().lower() != WORKER_STATUS_CLARIFICATION:
                    return {"error": "not_in_clarification", "user_id": tg}

                cur.execute(
                    """
                    SELECT id, payload FROM agency_visit_join_requests
                    WHERE user_id = %s ORDER BY id DESC LIMIT 1
                    """,
                    (tg,),
                )
                jrow = cur.fetchone()
                if not jrow:
                    return None
                join_id = int(jrow[0])
                pl = _json_loads(jrow[1])
                req_flags = list(pl.get("clarification_flags") or [])
                if not isinstance(req_flags, list) or not req_flags:
                    return {"error": "no_active_flags", "user_id": tg}

                for k, v in patch.items():
                    pl[k] = v

                kept: list[str] = []
                for code in req_flags:
                    c = str(code or "").strip().lower()
                    if c in VALID_CLARIFICATION_FLAG_CODES and not _flag_satisfied(c, pl):
                        kept.append(c)
                pl["clarification_flags"] = kept

                returned = False
                if not kept:
                    returned = True
                    for k in ("clarification_note", "clarification_requested_at", "clarification_flags"):
                        pl.pop(k, None)
                    cur.execute(
                        "UPDATE workers SET status = %s WHERE user_id = %s",
                        (WORKER_STATUS_PENDING_REVIEW, tg),
                    )
                    sync_stage = "new"
                else:
                    sync_stage = "in_progress"

                pl_json = json.dumps(pl, ensure_ascii=False, default=str)
                cur.execute(
                    "UPDATE agency_visit_join_requests SET payload = %s::jsonb WHERE id = %s",
                    (pl_json, join_id),
                )
        _sync_hrm_crm_card_for_join_request(join_id, tg, stage=sync_stage, payload_dict=pl)
        return {
            "user_id": tg,
            "join_id": join_id,
            "remaining_flags": kept,
            "returned_to_review": returned,
        }
    except Exception:
        logger.exception("apply_join_clarification_patch max_uid=%s", max_user_id)
        return None


def acknowledge_join_clarification_note_only(max_user_id: int) -> dict[str, Any] | None:
    tg = worker_tg_id_for_max(int(max_user_id))
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COALESCE(status, '') FROM workers WHERE user_id = %s LIMIT 1",
                    (tg,),
                )
                wrow = cur.fetchone()
                if not wrow or str(wrow[0] or "").strip().lower() != WORKER_STATUS_CLARIFICATION:
                    return {"error": "not_in_clarification", "user_id": tg}

                cur.execute(
                    """
                    SELECT id, payload FROM agency_visit_join_requests
                    WHERE user_id = %s ORDER BY id DESC LIMIT 1
                    """,
                    (tg,),
                )
                jrow = cur.fetchone()
                if not jrow:
                    return None
                join_id = int(jrow[0])
                pl = _json_loads(jrow[1])
                flags = pl.get("clarification_flags") if isinstance(pl.get("clarification_flags"), list) else []
                if flags:
                    return {"error": "flags_remain", "user_id": tg}

                for k in ("clarification_note", "clarification_requested_at", "clarification_flags"):
                    pl.pop(k, None)
                cur.execute(
                    "UPDATE workers SET status = %s WHERE user_id = %s",
                    (WORKER_STATUS_PENDING_REVIEW, tg),
                )
                pl_json = json.dumps(pl, ensure_ascii=False, default=str)
                cur.execute(
                    "UPDATE agency_visit_join_requests SET payload = %s::jsonb WHERE id = %s",
                    (pl_json, join_id),
                )
        _sync_hrm_crm_card_for_join_request(join_id, tg, stage="new", payload_dict=pl)
        return {"user_id": tg, "join_id": join_id, "returned_to_review": True}
    except Exception:
        logger.exception("acknowledge_join_clarification_note_only")
        return None
