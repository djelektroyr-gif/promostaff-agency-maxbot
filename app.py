"""
PROMOSTAFF Agency — MAX webhook (Timeweb / локально).
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

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


def _funnel_metrics() -> dict:
    out = {
        "incomplete_total": 0,
        "incomplete_warm": 0,
        "ready_24h": 0,
        "ready_72h": 0,
        "recent_steps": [],
        "recent_incomplete_users": [],
        "db_error": "",
    }
    if not DATABASE_URL:
        return out
    try:
        from funnel_db import connection

        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM agency_max_funnel
                    WHERE funnel_completed_at IS NULL
                      AND state IS NOT NULL
                      AND (state LIKE 'reg\\_%' ESCAPE '\\' OR state LIKE 'waiting%%')
                    """
                )
                out["incomplete_total"] = int((cur.fetchone() or [0])[0] or 0)

                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM agency_max_funnel
                    WHERE funnel_completed_at IS NULL
                      AND state IS NOT NULL
                      AND (state LIKE 'reg\\_%' ESCAPE '\\' OR state LIKE 'waiting%%')
                      AND funnel_phone_reached_at IS NOT NULL
                    """
                )
                out["incomplete_warm"] = int((cur.fetchone() or [0])[0] or 0)

                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM agency_max_funnel
                    WHERE funnel_completed_at IS NULL
                      AND state IS NOT NULL
                      AND (state LIKE 'reg\\_%' ESCAPE '\\' OR state LIKE 'waiting%%')
                      AND funnel_last_step_at IS NOT NULL
                      AND funnel_last_step_at < NOW() - INTERVAL '24 hours'
                      AND funnel_reminder_24h_sent_at IS NULL
                    """
                )
                out["ready_24h"] = int((cur.fetchone() or [0])[0] or 0)

                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM agency_max_funnel
                    WHERE funnel_completed_at IS NULL
                      AND state IS NOT NULL
                      AND (state LIKE 'reg\\_%' ESCAPE '\\' OR state LIKE 'waiting%%')
                      AND funnel_phone_reached_at IS NOT NULL
                      AND funnel_reminder_24h_sent_at IS NOT NULL
                      AND funnel_reminder_72h_sent_at IS NULL
                      AND funnel_last_step_at IS NOT NULL
                      AND funnel_last_step_at < NOW() - INTERVAL '72 hours'
                    """
                )
                out["ready_72h"] = int((cur.fetchone() or [0])[0] or 0)

                cur.execute(
                    """
                    SELECT COALESCE(NULLIF(TRIM(funnel_last_step), ''), state, '(нет)') AS step,
                           COUNT(*) AS cnt
                    FROM agency_max_funnel
                    WHERE funnel_completed_at IS NULL
                    GROUP BY 1
                    ORDER BY cnt DESC
                    LIMIT 8
                    """
                )
                out["recent_steps"] = [(str(r[0]), int(r[1])) for r in (cur.fetchall() or [])]

                cur.execute(
                    """
                    SELECT max_user_id,
                           COALESCE(NULLIF(TRIM(funnel_last_step), ''), state, '(нет)') AS step,
                           funnel_last_step_at
                    FROM agency_max_funnel
                    WHERE funnel_completed_at IS NULL
                      AND state IS NOT NULL
                      AND (state LIKE 'reg\\_%' ESCAPE '\\' OR state LIKE 'waiting%%')
                    ORDER BY funnel_last_step_at DESC NULLS LAST
                    LIMIT 20
                    """
                )
                out["recent_incomplete_users"] = [
                    (int(r[0]), str(r[1] or "(нет)"), str(r[2] or "—"))
                    for r in (cur.fetchall() or [])
                ]
    except Exception as e:
        out["db_error"] = str(e)
    return out


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
        "admin": "/admin",
    }


@app.get("/admin")
async def admin():
    funnel = _funnel_metrics()
    return {
        "status": "ok",
        "message": "PROMOSTAFF AGENCY MAX admin",
        "standard": "docs/ADMIN_PANEL_STANDARD.md",
        "sections": [
            "metrics",
            "funnel",
            "operations",
            "audit",
        ],
        "metrics": {
            "database_url_configured": bool(DATABASE_URL),
            "funnel_reminders_enabled": bool(
                FUNNEL_REMINDERS_ENABLED and DATABASE_URL and MAX_TOKEN
            ),
            "admin_max_ids_count": len(ADMIN_MAX_USER_IDS),
            "funnel_incomplete_total": funnel["incomplete_total"],
            "funnel_incomplete_warm": funnel["incomplete_warm"],
            "funnel_ready_24h": funnel["ready_24h"],
            "funnel_ready_72h": funnel["ready_72h"],
        },
        "quick_links": {
            "ui": "/admin/ui",
            "health": "/health",
        },
    }


@app.get("/admin/ui", response_class=HTMLResponse)
async def admin_ui(run: str | None = Query(default=None), confirm: int = Query(default=0)):
    action_note = ""
    action_error = ""
    if run == "funnel_scan":
        if confirm != 1:
            action_note = "Скан не запущен: добавьте `?run=funnel_scan&confirm=1`."
        elif not (FUNNEL_REMINDERS_ENABLED and DATABASE_URL and MAX_TOKEN):
            action_error = (
                "Скан не запущен: проверьте FUNNEL_REMINDERS_ENABLED=1, DATABASE_URL и MAX_TOKEN."
            )
        else:
            try:
                from registration_funnel_reminders import process_agency_funnel_reminders

                await process_agency_funnel_reminders()
                action_note = "One-shot скан напоминаний выполнен успешно."
            except Exception as e:
                action_error = f"Ошибка ручного скана: {e}"
    funnel = _funnel_metrics()
    cards = [
        ("DB", "OK" if DATABASE_URL else "OFF"),
        ("MAX token", "OK" if MAX_TOKEN else "OFF"),
        ("Admins", str(len(ADMIN_MAX_USER_IDS))),
        (
            "Reminders",
            "ON" if (FUNNEL_REMINDERS_ENABLED and DATABASE_URL and MAX_TOKEN) else "OFF",
        ),
        ("Funnel incomplete", str(funnel["incomplete_total"])),
        ("Funnel warm", str(funnel["incomplete_warm"])),
        ("Ready 24h", str(funnel["ready_24h"])),
        ("Ready 72h", str(funnel["ready_72h"])),
    ]
    cards_html = "\n".join(
        f'<div class="card"><div class="title">{title}</div><div class="value">{value}</div></div>'
        for title, value in cards
    )
    if funnel["recent_steps"]:
        rows = "\n".join(
            f"<tr><td>{step}</td><td>{cnt}</td></tr>" for step, cnt in funnel["recent_steps"]
        )
    else:
        rows = '<tr><td colspan="2">Нет данных</td></tr>'
    if funnel["recent_incomplete_users"]:
        users_rows = "\n".join(
            f"<tr><td>{uid}</td><td>{step}</td><td>{last_at}</td></tr>"
            for uid, step, last_at in funnel["recent_incomplete_users"]
        )
    else:
        users_rows = '<tr><td colspan="3">Нет данных</td></tr>'
    db_note = (
        f"<p class='warn'>DB error: {funnel['db_error']}</p>" if funnel.get("db_error") else ""
    )
    return f"""
    <html lang="ru">
      <head>
        <meta charset="utf-8"/>
        <title>PROMOSTAFF AGENCY MAX Admin</title>
        <style>
          body {{ font-family: Inter, Arial, sans-serif; margin: 24px; background: #fafafa; color: #1a1a1a; }}
          .grid {{ display: grid; grid-template-columns: repeat(4, minmax(160px, 1fr)); gap: 12px; margin: 16px 0; }}
          .card {{ background: #fff; border: 1px solid #ddd; border-radius: 10px; padding: 12px; }}
          .title {{ font-size: 12px; color: #666; }}
          .value {{ font-size: 22px; font-weight: 700; margin-top: 6px; }}
          .box {{ background: #fff; border: 1px solid #ddd; border-radius: 10px; padding: 12px; margin-top: 12px; }}
          a.btn {{ display: inline-block; padding: 8px 10px; border: 1px solid #bbb; border-radius: 8px; text-decoration: none; color: #222; margin-right: 8px; margin-bottom: 8px; }}
          table {{ border-collapse: collapse; width: 100%; margin-top: 8px; }}
          th, td {{ border: 1px solid #e1e1e1; padding: 8px; font-size: 14px; }}
          th {{ background: #f5f5f5; text-align: left; }}
          .muted {{ color: #666; font-size: 13px; }}
          .warn {{ color: #b54708; font-size: 13px; }}
          code {{ background: #f3f3f3; padding: 2px 6px; border-radius: 6px; }}
        </style>
      </head>
      <body>
        <h2>PROMOSTAFF AGENCY MAX — Admin</h2>
        <p class="muted">Стандарт: <code>docs/ADMIN_PANEL_STANDARD.md</code></p>
        <div class="grid">{cards_html}</div>

        <div class="box">
          <h3>Быстрые действия</h3>
          <a class="btn" href="/health">Health</a>
          <a class="btn" href="/admin">Admin JSON</a>
          <a class="btn" href="/admin/ui">Обновить</a>
          <a class="btn" href="/admin/ui?run=funnel_scan&confirm=1">Запустить one-shot скан напоминаний</a>
          <p class="muted">Для ручного прогона напоминаний используйте запущенный фоновый цикл (FUNNEL_REMINDERS_ENABLED=1).</p>
          {f"<p class='muted'>{action_note}</p>" if action_note else ""}
          {f"<p class='warn'>{action_error}</p>" if action_error else ""}
        </div>

        <div class="box">
          <h3>Funnel breakdown</h3>
          <p class="muted">Незавершённые сценарии по последнему шагу.</p>
          <table>
            <thead><tr><th>Шаг</th><th>Кол-во</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
          {db_note}
        </div>

        <div class="box">
          <h3>Последние незавершённые пользователи</h3>
          <p class="muted">Последние MAX users с незавершённой воронкой.</p>
          <table>
            <thead><tr><th>MAX user ID</th><th>Шаг</th><th>Последняя активность</th></tr></thead>
            <tbody>{users_rows}</tbody>
          </table>
        </div>
      </body>
    </html>
    """


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
