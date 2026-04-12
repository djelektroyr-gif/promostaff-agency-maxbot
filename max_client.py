"""Минимальные вызовы Platform API MAX (исходящие сообщения)."""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


async def post_message(token: str, user_id: int, body: dict[str, Any]) -> bool:
    """POST /messages?user_id=…"""
    if not token or not user_id:
        return False
    url = f"https://platform-api.max.ru/messages?user_id={int(user_id)}"
    headers = {"Authorization": token, "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            r = await client.post(url, headers=headers, content=json.dumps(body, ensure_ascii=False).encode("utf-8"))
            if r.status_code >= 400:
                logger.warning("MAX post_message failed: %s %s", r.status_code, r.text[:500])
                return False
    except Exception:
        logger.exception("MAX post_message error")
        return False
    return True


async def post_answer(token: str, callback_id: str, payload: dict[str, Any]) -> bool:
    """POST /answers?callback_id=…"""
    if not token or not callback_id:
        return False
    url = f"https://platform-api.max.ru/answers?callback_id={callback_id}"
    headers = {"Authorization": token, "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            r = await client.post(url, headers=headers, content=json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            if r.status_code >= 400:
                logger.warning("MAX post_answer failed: %s %s", r.status_code, r.text[:500])
                return False
    except Exception:
        logger.exception("MAX post_answer error")
    return True
