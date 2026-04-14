"""
Обработка MAX: клон сценария PROMOSTAFF-AGENCY BOT (меню, колбэки, FSM в visit_flows).
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from config import MAX_TOKEN
from funnel_store import funnel_sync_session
from max_client import post_answer, post_message

import visit_card
import visit_flows

logger = logging.getLogger(__name__)


async def _sync_funnel(max_uid: int) -> None:
    await asyncio.to_thread(
        funnel_sync_session,
        max_uid,
        visit_flows.SESSIONS.get(max_uid),
    )


def _max_uid_from_update(update_type: str, body: dict[str, Any]) -> int | None:
    if update_type == "user_added":
        u = body.get("user") or {}
        uid = u.get("user_id")
        return int(uid) if uid is not None else None
    if update_type == "bot_started":
        u = body.get("user") or {}
        uid = u.get("user_id")
        return int(uid) if uid is not None else None
    if update_type == "message_created":
        msg = body.get("message") or {}
        sender = msg.get("sender") or {}
        if sender.get("is_bot"):
            return None
        uid = sender.get("user_id")
        return int(uid) if uid is not None else None
    if update_type == "message_callback":
        cb = body.get("callback") or {}
        u = cb.get("user") or {}
        uid = u.get("user_id")
        return int(uid) if uid is not None else None
    return None


def _sender_from_message(body: dict[str, Any]) -> dict[str, Any] | None:
    msg = body.get("message") or {}
    s = msg.get("sender")
    return s if isinstance(s, dict) else None


async def _send_message(max_uid: int, body: dict[str, Any]) -> None:
    await post_message(MAX_TOKEN, max_uid, body)


async def _answer_message(callback_id: str, max_uid: int, msg: dict[str, Any]) -> None:
    ok = await post_answer(
        MAX_TOKEN,
        callback_id,
        {"notification": " ", "message": msg},
    )
    if not ok:
        logger.warning("post_answer failed, sending new message")
        await _send_message(max_uid, msg)


async def process_update(body: dict[str, Any]) -> None:
    update_type = body.get("update_type") or ""
    max_uid = _max_uid_from_update(update_type, body)
    logger.info("MAX update: type=%r max_uid=%r", update_type, max_uid)

    if update_type in ("bot_started", "user_added") and max_uid is not None:
        visit_flows.clear_session(max_uid)
        await _send_message(max_uid, visit_card.message_main_menu())
        await _sync_funnel(max_uid)
        return

    if update_type == "message_created" and max_uid is not None:
        msg = body.get("message") or {}
        inner = msg.get("body") or {}
        text = (inner.get("text") or "").strip()
        sender = _sender_from_message(body)

        if re.match(r"^/(start|старт)\b", text, re.I):
            visit_flows.clear_session(max_uid)
            await _send_message(max_uid, visit_card.message_main_menu())
            await _sync_funnel(max_uid)
            return
        if re.match(r"^(меню|menu)\b", text, re.I):
            visit_flows.clear_session(max_uid)
            await _send_message(max_uid, visit_card.message_main_menu())
            await _sync_funnel(max_uid)
            return

        reply = await visit_flows.process_text(max_uid, text, sender)
        await _sync_funnel(max_uid)
        if reply is not None:
            await _send_message(max_uid, reply)
        return

    if update_type == "message_callback" and max_uid is not None:
        cb = body.get("callback") or {}
        callback_id = (cb.get("callback_id") or "").strip()
        payload = (cb.get("payload") or "").strip()
        if not callback_id:
            return

        if payload == "none":
            await post_answer(MAX_TOKEN, callback_id, {"notification": " "})
            return

        if payload in ("main_menu", "back", "back_to_main"):
            visit_flows.clear_session(max_uid)
            await _answer_message(callback_id, max_uid, visit_card.message_main_menu())
            await _sync_funnel(max_uid)
            return

        if payload == "calculate":
            msg = visit_flows.start_order(max_uid)
            await _answer_message(callback_id, max_uid, msg)
            await _sync_funnel(max_uid)
            return

        if payload == "ask_question":
            msg = visit_flows.start_question(max_uid)
            await _answer_message(callback_id, max_uid, msg)
            await _sync_funnel(max_uid)
            return

        if payload == "fill_anketa":
            msg = visit_flows.start_join(max_uid)
            await _answer_message(callback_id, max_uid, msg)
            await _sync_funnel(max_uid)
            return

        if payload.startswith("pos_"):
            msg = visit_flows.join_select_position(max_uid, payload)
            if msg is not None:
                await _answer_message(callback_id, max_uid, msg)
            else:
                await post_answer(MAX_TOKEN, callback_id, {"notification": " "})
            await _sync_funnel(max_uid)
            return

        visit_flows.clear_session(max_uid)
        static_msg = visit_card.message_for_static_payload(payload)
        if static_msg is not None:
            await _answer_message(callback_id, max_uid, static_msg)
        else:
            await post_answer(MAX_TOKEN, callback_id, {"notification": " "})
        await _sync_funnel(max_uid)
        return
