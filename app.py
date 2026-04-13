"""
PROMOSTAFF Agency — MAX webhook (Timeweb / локально).
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from config import ADMIN_MAX_USER_IDS, MAX_TOKEN
from notify import smtp_configured
from handlers import process_update

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="PROMOSTAFF Agency MAX", version="0.1.0")


@app.get("/health")
async def health():
    ok = bool(MAX_TOKEN)
    return {
        "ok": True,
        "max_token_configured": ok,
        "smtp_configured": smtp_configured(),
        "admin_max_ids_count": len(ADMIN_MAX_USER_IDS),
    }


@app.get("/")
async def root():
    return {
        "service": "promostaff-agency-maxbot",
        "health": "/health",
        "webhook": "/webhook",
    }


@app.post("/webhook")
async def webhook(request: Request):
    if not MAX_TOKEN:
        logger.error("MAX_TOKEN не задан")
        return JSONResponse({"ok": False, "error": "MAX_TOKEN missing"}, status_code=503)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": True})

    if isinstance(body, dict):
        try:
            await process_update(body)
        except Exception:
            logger.exception("webhook handler error")
    return JSONResponse({"ok": True})
