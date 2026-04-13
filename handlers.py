"""
Обработка входящих апдейтов MAX: визитка (меню, разделы, inline-кнопки).
"""
from __future__ import annotations

import logging
import re
from typing import Any

from config import MAX_TOKEN
from max_client import post_answer, post_message

import visit_card

logger = logging.getLogger(__name__)


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


async def _send_message(max_uid: int, body: dict[str, Any]) -> None:
    await post_message(MAX_TOKEN, max_uid, body)


async def _send_main_menu(max_uid: int) -> None:
    await _send_message(
        max_uid,
        {
            "text": visit_card.text_welcome(),
            "format": "markdown",
            "attachments": visit_card.attachments_main_menu(),
        },
    )


async def process_update(body: dict[str, Any]) -> None:
    update_type = body.get("update_type") or ""
    max_uid = _max_uid_from_update(update_type, body)
    logger.info("MAX update: type=%r max_uid=%r", update_type, max_uid)

    if update_type in ("bot_started", "user_added") and max_uid is not None:
        await _send_main_menu(max_uid)
        return

    if update_type == "message_created" and max_uid is not None:
        msg = body.get("message") or {}
        inner = msg.get("body") or {}
        text = (inner.get("text") or "").strip()
        if re.match(r"^/(start|старт)\b", text, re.I):
            await _send_main_menu(max_uid)
            return
        if re.match(r"^(меню|menu)\b", text, re.I):
            await _send_main_menu(max_uid)
            return
        return

    if update_type == "message_callback" and max_uid is not None:
        cb = body.get("callback") or {}
        callback_id = (cb.get("callback_id") or "").strip()
        payload = (cb.get("payload") or "").strip()
        if not callback_id:
            return
        msg = visit_card.message_for_payload(payload)
        if msg is not None:
            ok = await post_answer(
                MAX_TOKEN,
                callback_id,
                {
                    "notification": " ",
                    "message": msg,
                },
            )
            if not ok:
                logger.warning("post_answer failed for payload=%r, sending new message", payload)
                await _send_message(max_uid, msg)
        else:
            await post_answer(MAX_TOKEN, callback_id, {"notification": " "})
        return
