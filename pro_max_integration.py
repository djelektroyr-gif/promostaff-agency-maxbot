"""
Та же регистрация MAX, что в promostaff-bot/max_webhook/max_bot.py: общие users.state и колбэки.
Визитка агентства делегирует сюда все апдейты, пока пользователь в активной воронке PRO.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from agency_pro_vendor import ensure_promostaff_vendor_path

logger = logging.getLogger(__name__)


def should_delegate_pro_max(max_user_id: int) -> bool:
    if not ensure_promostaff_vendor_path():
        return False
    from config import DATABASE_URL

    if not (DATABASE_URL or "").strip():
        return False
    try:
        from services.registration_states import REG_FLOW_ACTIVE
        from services.user_service import ensure_max_user_row, get_user
    except Exception:
        return False
    try:
        row = ensure_max_user_row(max_user_id, None)
        if not row:
            return False
        u = get_user(int(row["tg_id"]))
        if not u:
            return False
        st = (u.get("state") or "").strip()
        if st in REG_FLOW_ACTIVE:
            return True
        if st == "waiting_consent":
            return True
        return False
    except Exception:
        logger.debug("should_delegate_pro_max skip", exc_info=True)
        return False


def is_pro_registration_payload(payload: str) -> bool:
    p = (payload or "").strip()
    if not p or not ensure_promostaff_vendor_path():
        return False
    try:
        from services.registration_ids import (
            CB_EXP_13,
            CB_EXP_GT3,
            CB_EXP_LT1,
            CB_FL_LK_NA,
            CB_FL_STAY,
            CB_M2_NO,
            CB_M2_YES,
            CB_MAX_REG_SYNC,
            CB_MED_NO,
            CB_MED_PROC,
            CB_MED_YES,
            CB_MERGE_NO,
            CB_MERGE_YES,
            CB_NAV_BACK_STEP,
            CB_REG_EXECUTOR,
            CB_REG_INVITE,
            CB_REG_LEGAL,
            CB_SE_LK_CONTINUE,
            CB_SE_NPD_OK,
            CB_TAX_IP,
            CB_TAX_PHYSICAL,
            CB_TAX_SELF,
            CB_TRV_NEG,
            CB_TRV_NO,
            CB_TRV_YES,
            CB_VACANCY_NO,
            CB_VACANCY_YES,
        )
    except Exception:
        return False

    exact = {
        CB_REG_EXECUTOR,
        CB_REG_LEGAL,
        CB_REG_INVITE,
        CB_TAX_PHYSICAL,
        CB_TAX_SELF,
        CB_TAX_IP,
        CB_EXP_LT1,
        CB_EXP_13,
        CB_EXP_GT3,
        CB_FL_STAY,
        CB_FL_LK_NA,
        CB_VACANCY_YES,
        CB_VACANCY_NO,
        CB_MERGE_YES,
        CB_MERGE_NO,
        CB_SE_NPD_OK,
        CB_SE_LK_CONTINUE,
        CB_M2_YES,
        CB_M2_NO,
        CB_MED_YES,
        CB_MED_NO,
        CB_MED_PROC,
        CB_TRV_YES,
        CB_TRV_NO,
        CB_TRV_NEG,
        CB_NAV_BACK_STEP,
        CB_MAX_REG_SYNC,
        "consent:yes",
        "consent:no",
    }
    if p in exact:
        return True
    prefixes = (
        "profcat:",
        "regprof:",
        "exp:",
        "consent:",
        "vacancy:",
        "reg:",
        "tax:",
        "fl:",
        "merge:",
        "m2:",
        "se:",
        "med:",
        "trv:",
        "regnav:",
    )
    return any(p.startswith(pref) for pref in prefixes)


async def bootstrap_visit_worker_pro_max(max_user_id: int) -> None:
    """После согласия во визитке — те же поля users и шаг рассылки, что у PRO (max_bot)."""
    if not ensure_promostaff_vendor_path():
        raise RuntimeError("promostaff-bot vendor not found")
    from config import PD_CONSENT_VERSION
    from max_webhook.max_bot import _send_vacancy_step_max
    from services.user_service import ensure_max_user_row, update_user

    row = ensure_max_user_row(max_user_id, None)
    tg_id = int(row["tg_id"])
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    update_user(
        tg_id,
        {
            "role": "worker",
            "account_type": "executor",
            "pd_consent_version": PD_CONSENT_VERSION,
            "pd_consent_at": now,
            "pro_access_source": "agency_visit_worker",
            "pro_access_at": now,
            "state": "waiting_vacancy_mailing",
        },
    )
    await _send_vacancy_step_max(max_user_id, tg_id)


async def process_promostaff_max_update(body: dict[str, Any]) -> None:
    if not ensure_promostaff_vendor_path():
        return
    from max_webhook.max_bot import process_max_update

    await process_max_update(body)


def init_promostaff_postgres(database_url: str) -> None:
    if not ensure_promostaff_vendor_path():
        return
    url = (database_url or "").strip()
    if not url:
        return
    from database.postgres_models import init_postgres

    init_postgres(url)
