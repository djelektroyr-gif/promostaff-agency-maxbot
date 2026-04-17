"""Минимальные вызовы Platform API MAX (исходящие сообщения)."""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE = "https://platform-api.max.ru"

# Один клиент с keep-alive: новый AsyncClient на каждый вызов даёт новое TCP/TLS к platform-api
# и заметные задержки между шагами визитки.
_http: httpx.AsyncClient | None = None


async def get_http_client() -> httpx.AsyncClient:
    global _http
    if _http is None:
        _http = httpx.AsyncClient(
            timeout=httpx.Timeout(25.0, connect=15.0),
            limits=httpx.Limits(max_keepalive_connections=32, max_connections=64),
            trust_env=False,
        )
    return _http


async def close_http_client() -> None:
    """Закрыть соединения (lifespan приложения)."""
    global _http
    if _http is not None:
        await _http.aclose()
        _http = None


async def post_message(token: str, user_id: int, body: dict[str, Any]) -> bool:
    """POST /messages?user_id=…"""
    if not token or not user_id:
        return False
    url = f"{BASE}/messages"
    params = {"user_id": int(user_id)}
    headers = {"Authorization": token, "Content-Type": "application/json"}
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    try:
        client = await get_http_client()
        r = await client.post(url, params=params, headers=headers, content=data)
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
    url = f"{BASE}/answers"
    params = {"callback_id": callback_id}
    headers = {"Authorization": token, "Content-Type": "application/json"}
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        client = await get_http_client()
        r = await client.post(url, params=params, headers=headers, content=data)
        if r.status_code >= 400:
            logger.warning("MAX post_answer failed: %s %s", r.status_code, r.text[:500])
            return False
    except Exception:
        logger.exception("MAX post_answer error")
        return False
    return True
