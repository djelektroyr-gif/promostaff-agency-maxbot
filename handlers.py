"""
Обработка MAX: визитка как в Telegram, плюс нативные возможности MAX
(в т.ч. короткий текст в `notification` при ответе на callback — «всплывашка» у кнопки).
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
    body = dict(body)
    body.pop("notification", None)
    await post_message(MAX_TOKEN, max_uid, body)


async def _answer_message(callback_id: str, max_uid: int, msg: dict[str, Any]) -> None:
    msg = dict(msg)
    raw = msg.pop("notification", None)
    notif = (raw if isinstance(raw, str) else None) or " "
    notif = notif.strip() or " "
    api_msg = {k: v for k, v in msg.items()}
    ok = await post_answer(
        MAX_TOKEN,
        callback_id,
        {"notification": notif[:200], "message": api_msg},
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

        reply = await visit_flows.process_text(max_uid, text, sender, inner)
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

        if payload == "ask_manager":
            msg = visit_flows.start_question(max_uid)
            await _answer_message(callback_id, max_uid, msg)
            await _sync_funnel(max_uid)
            return

        if payload in ("contact_show_phone", "contact_show_email"):
            from config import CONTACT_EMAIL, CONTACT_PHONE

            note = CONTACT_PHONE if payload == "contact_show_phone" else CONTACT_EMAIL
            await post_answer(
                MAX_TOKEN,
                callback_id,
                {"notification": (note or "")[:200]},
            )
            return

        if payload.startswith("vac_apply_"):
            msg = visit_flows.join_from_vacancy(max_uid, payload)
            if msg is not None:
                await _answer_message(callback_id, max_uid, msg)
            else:
                await post_answer(MAX_TOKEN, callback_id, {"notification": " "})
            await _sync_funnel(max_uid)
            return

        if payload == "fill_anketa":
            msg = visit_flows.start_join(max_uid)
            await _answer_message(callback_id, max_uid, msg)
            await _sync_funnel(max_uid)
            return

        sender_cb = cb.get("user") if isinstance(cb.get("user"), dict) else None
        flow_reply = await visit_flows.process_callback(max_uid, payload, sender_cb)
        if flow_reply is not None:
            await _answer_message(callback_id, max_uid, flow_reply)
            await _sync_funnel(max_uid)
            return

        static_msg = visit_card.message_for_static_payload(payload)
        if static_msg is not None:
            visit_flows.clear_session(max_uid)
            await _answer_message(callback_id, max_uid, static_msg)
        elif visit_card.is_visit_flow_payload(payload):
            await post_answer(MAX_TOKEN, callback_id, {"notification": " "})
        else:
            visit_flows.clear_session(max_uid)
            await post_answer(MAX_TOKEN, callback_id, {"notification": " "})
        await _sync_funnel(max_uid)
        return
