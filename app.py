"""
PROMOSTAFF Agency — MAX webhook (Timeweb / локально).
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from config import (
    ADMIN_MAX_USER_IDS,
    DATABASE_URL,
    FUNNEL_REMINDERS_ENABLED,
    FUNNEL_REMINDERS_INTERVAL_SEC,
    MAX_TOKEN,
)
from notify import smtp_configured
from handlers import process_update

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if DATABASE_URL:
        try:
            from funnel_db import init_schema

            init_schema()
        except Exception:
            logger.exception("funnel init_schema")

    stop = asyncio.Event()
    reminder_task: asyncio.Task | None = None
    if FUNNEL_REMINDERS_ENABLED and DATABASE_URL and MAX_TOKEN:

        async def _reminder_loop() -> None:
            from registration_funnel_reminders import process_agency_funnel_reminders

            while not stop.is_set():
                await process_agency_funnel_reminders()
                try:
                    await asyncio.wait_for(
                        stop.wait(),
                        timeout=max(30, FUNNEL_REMINDERS_INTERVAL_SEC),
                    )
                except asyncio.TimeoutError:
                    pass

        reminder_task = asyncio.create_task(_reminder_loop())

    yield

    stop.set()
    if reminder_task is not None:
        reminder_task.cancel()
        try:
            await reminder_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="PROMOSTAFF Agency MAX", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health():
    ok = bool(MAX_TOKEN)
    return {
        "ok": True,
        "max_token_configured": ok,
        "database_url_configured": bool(DATABASE_URL),
        "funnel_reminders_enabled": bool(
            FUNNEL_REMINDERS_ENABLED and DATABASE_URL and MAX_TOKEN
        ),
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
