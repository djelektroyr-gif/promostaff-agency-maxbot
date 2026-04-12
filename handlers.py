"""
Обработка входящих апдейтов MAX. Здесь позже — сценарий визитки (меню, edit, кнопки).
Сейчас: приветствие на /start и bot_started/user_added.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from config import MAX_TOKEN
from max_client import post_answer, post_message

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


async def _send_plain(max_uid: int, text: str, *, fmt: str | None = None) -> None:
    body: dict = {"text": text}
    if fmt:
        body["format"] = fmt
    await post_message(MAX_TOKEN, max_uid, body)


async def process_update(body: dict[str, Any]) -> None:
    update_type = body.get("update_type") or ""
    max_uid = _max_uid_from_update(update_type, body)
    logger.info("MAX update: type=%r max_uid=%r", update_type, max_uid)

    if update_type in ("bot_started", "user_added") and max_uid is not None:
        await _send_plain(
            max_uid,
            "👋 Добро пожаловать в PROMOSTAFF Agency.\n\n"
            "Сценарий визитки подключим в следующих коммитах. "
            "Отправьте /start для проверки.",
        )
        return

    if update_type == "message_created" and max_uid is not None:
        msg = body.get("message") or {}
        inner = msg.get("body") or {}
        text = (inner.get("text") or "").strip()
        if re.match(r"^/(start|старт)\b", text, re.I):
            await _send_plain(
                max_uid,
                "🏢 *PROMOSTAFF Agency*\n\n"
                "Визитка в MAX — в разработке. Здесь будут разделы и кнопки, как в Telegram-боте агентства.",
                fmt="markdown",
            )
        return

    if update_type == "message_callback" and max_uid is not None:
        cb = body.get("callback") or {}
        callback_id = cb.get("callback_id") or ""
        if callback_id:
            await post_answer(MAX_TOKEN, callback_id, {"notification": " "})
        return
