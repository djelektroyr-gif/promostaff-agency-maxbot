"""
PROMOSTAFF Agency — MAX webhook (Timeweb / локально).
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, Response

from config import (
    ADMIN_MAX_USER_IDS,
    DATABASE_URL,
    FUNNEL_REMINDERS_ENABLED,
    FUNNEL_REMINDERS_INTERVAL_SEC,
    MAX_TOKEN,
)
from notify import smtp_configured
from handlers import process_update
from max_client import post_message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _parse_broadcast_filter(raw: str) -> dict[str, str | bool]:
    out: dict[str, str | bool] = {"position": "", "experience": "", "priority": False}
    text = (raw or "").strip()
    if not text or text.lower() == "all":
        return out
    if text.lower() == "priority":
        out["priority"] = True
        return out
    parts = [p.strip() for p in text.replace(";", ",").split(",") if p.strip()]
    for p in parts:
        if "=" not in p:
            continue
        k, v = p.split("=", 1)
        key = k.strip().lower()
        val = v.strip()
        if key in ("position", "должность"):
            out["position"] = val
        elif key in ("experience", "опыт"):
            out["experience"] = val
        elif key in ("priority", "приоритет"):
            out["priority"] = val in ("1", "true", "yes", "да")
    return out


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


def _visitcard_metrics() -> dict:
    out = {"orders": 0, "join": 0, "questions": 0, "db_error": ""}
    if not DATABASE_URL:
        return out
    try:
        from funnel_db import get_visitcard_stats

        stats = get_visitcard_stats()
        stats["db_error"] = ""
        return stats
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
        try:
            from pro_max_integration import init_promostaff_postgres

            init_promostaff_postgres(DATABASE_URL)
        except Exception:
            logger.exception("promostaff init_postgres (vendor/registracija PRO v MAX)")

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
    visit = _visitcard_metrics()
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
            "visit_orders": visit["orders"],
            "visit_join": visit["join"],
            "visit_questions": visit["questions"],
        },
        "quick_links": {
            "ui": "/admin/ui",
            "health": "/health",
        },
    }


@app.get("/admin/ui", response_class=HTMLResponse)
async def admin_ui(
    run: str | None = Query(default=None),
    confirm: int = Query(default=0),
    visit_kind: str = Query(default="orders"),
    date_from: str = Query(default=""),
    date_to: str = Query(default=""),
):
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
    visit = _visitcard_metrics()
    visit_rows = []
    try:
        from funnel_db import list_visit_rows

        visit_rows = list_visit_rows(visit_kind, 20, date_from=date_from, date_to=date_to)
    except Exception:
        logger.exception("list_visit_rows")
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
        ("Visit orders", str(visit["orders"])),
        ("Visit join", str(visit["join"])),
        ("Visit questions", str(visit["questions"])),
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
    db_errors = []
    if funnel.get("db_error"):
        db_errors.append(f"Funnel DB error: {funnel['db_error']}")
    if visit.get("db_error"):
        db_errors.append(f"Visitcard DB error: {visit['db_error']}")
    db_note = "".join([f"<p class='warn'>{e}</p>" for e in db_errors])
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
          <h3>Рассылка вакансии (MAX)</h3>
          <p class="muted">Сегментированная отправка предложения о работе по базе MAX.</p>
          <form method="post" action="/admin/broadcast">
            <label>Фильтр аудитории:</label><br/>
            <input style="width: 100%; max-width: 720px;" name="filter_text" value="all" placeholder="all | priority | position=Хостес | experience=Более 3 лет"/><br/><br/>
            <label>Текст вакансии:</label><br/>
            <textarea name="message_text" rows="6" style="width: 100%; max-width: 720px;" placeholder="Опишите вакансию, условия и как откликнуться"></textarea><br/><br/>
            <button type="submit" name="action" value="preview">Предпросмотр</button>
            <button type="submit" name="action" value="send">Отправить рассылку</button>
          </form>
          <p class="muted">Примеры фильтров: <code>all</code>, <code>priority</code>, <code>position=Промоутер,priority=1</code></p>
        </div>

        <div class="box">
          <h3>Visitcard leads</h3>
          <p class="muted">Фильтр лидов по типу и дате.</p>
          <form method="get" action="/admin/ui">
            <label>Тип:
              <select name="visit_kind">
                <option value="orders" {"selected" if visit_kind == "orders" else ""}>orders</option>
                <option value="join" {"selected" if visit_kind == "join" else ""}>join</option>
                <option value="questions" {"selected" if visit_kind == "questions" else ""}>questions</option>
              </select>
            </label>
            <label> c: <input name="date_from" value="{date_from}" placeholder="YYYY-MM-DD"/></label>
            <label> по: <input name="date_to" value="{date_to}" placeholder="YYYY-MM-DD"/></label>
            <button type="submit">Применить</button>
          </form>
          <p class="muted"><a href="/admin/export?kind={visit_kind}&date_from={date_from}&date_to={date_to}">Скачать CSV по фильтру</a></p>
          <table>
            <thead><tr><th>ID</th><th>Дата</th><th>User</th><th>Preview</th></tr></thead>
            <tbody>
              {"".join([f"<tr><td>{r.get('id')}</td><td>{r.get('created_at')}</td><td>{r.get('username') or r.get('user_id')}</td><td>{((r.get('question') or r.get('payload') or '')[:120]).replace('<','&lt;')}</td></tr>" for r in visit_rows]) or "<tr><td colspan='4'>Нет данных</td></tr>"}
            </tbody>
          </table>
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


@app.get("/admin/export")
async def admin_export_csv(
    kind: str = Query(default="orders"),
    date_from: str = Query(default=""),
    date_to: str = Query(default=""),
):
    from funnel_db import list_visit_rows

    rows = list_visit_rows(kind, 1000, date_from=date_from, date_to=date_to)
    if not rows:
        return Response(content="id\n", media_type="text/csv")
    output = io.StringIO()
    if kind == "questions":
        cols = ["id", "created_at", "user_id", "username", "question"]
    else:
        cols = ["id", "created_at", "user_id", "username", "event_type", "contact_name", "phone", "city", "event_date", "total_cost"]
    writer = csv.DictWriter(output, fieldnames=cols)
    writer.writeheader()
    for r in rows:
        if kind == "questions":
            writer.writerow({k: r.get(k, "") for k in cols})
            continue
        payload_raw = r.get("payload") or "{}"
        try:
            payload = json.loads(payload_raw)
        except Exception:
            payload = {}
        writer.writerow(
            {
                "id": r.get("id"),
                "created_at": r.get("created_at"),
                "user_id": r.get("user_id"),
                "username": r.get("username"),
                "event_type": payload.get("event_type", ""),
                "contact_name": payload.get("contact_name", ""),
                "phone": payload.get("contact_phone", ""),
                "city": payload.get("city", ""),
                "event_date": payload.get("event_date", ""),
                "total_cost": payload.get("total_cost", 0),
            }
        )
    data = output.getvalue()
    headers = {"Content-Disposition": f'attachment; filename="visit_{kind}.csv"'}
    return Response(content=data, media_type="text/csv; charset=utf-8", headers=headers)


@app.post("/admin/broadcast", response_class=HTMLResponse)
async def admin_broadcast(
    filter_text: str = Form(default="all"),
    message_text: str = Form(default=""),
    action: str = Form(default="preview"),
):
    filt_raw = (filter_text or "all").strip() or "all"
    body = (message_text or "").strip()
    if len(body) < 5:
        return HTMLResponse(
            "<h3>Ошибка: слишком короткий текст рассылки.</h3><p><a href='/admin/ui'>Вернуться в админку</a></p>",
            status_code=400,
        )
    if not MAX_TOKEN:
        return HTMLResponse(
            "<h3>Ошибка: MAX_TOKEN не задан.</h3><p><a href='/admin/ui'>Вернуться в админку</a></p>",
            status_code=503,
        )
    from funnel_db import list_max_join_broadcast_targets

    filt = _parse_broadcast_filter(filt_raw)
    targets = list_max_join_broadcast_targets(
        position=str(filt.get("position") or ""),
        experience_years=str(filt.get("experience") or ""),
        priority_only=bool(filt.get("priority")),
        limit=1500,
    )
    if not targets:
        return HTMLResponse(
            f"<h3>По фильтру `{filt_raw}` получатели не найдены.</h3><p><a href='/admin/ui'>Вернуться в админку</a></p>",
            status_code=200,
        )
    preview_rows = "".join(
        [
            f"<tr><td>{t.get('user_id')}</td><td>{(t.get('username') or '').replace('<','&lt;')}</td><td>{(t.get('position') or '').replace('<','&lt;')}</td><td>{(t.get('experience_years') or '').replace('<','&lt;')}</td></tr>"
            for t in targets[:10]
        ]
    )
    if action != "send":
        return HTMLResponse(
            f"""
            <h3>Предпросмотр рассылки</h3>
            <p>Фильтр: <code>{filt_raw}</code></p>
            <p>Потенциальных получателей: {len(targets)}</p>
            <table border="1" cellpadding="6" cellspacing="0">
              <thead><tr><th>User ID</th><th>Username</th><th>Position</th><th>Experience</th></tr></thead>
              <tbody>{preview_rows or "<tr><td colspan='4'>Нет данных</td></tr>"}</tbody>
            </table>
            <p style="margin-top:12px;"><a href='/admin/ui'>Назад</a></p>
            """,
            status_code=200,
        )
    sent = 0
    failed = 0
    payload = {
        "text": f"📣 *Предложение о работе*\n\n{body}\n\nЕсли интересно, ответьте на это сообщение.",
        "format": "markdown",
    }
    for t in targets:
        ok = await post_message(MAX_TOKEN, int(t["user_id"]), payload)
        if ok:
            sent += 1
        else:
            failed += 1
    return HTMLResponse(
        f"""
        <h3>Рассылка завершена</h3>
        <p>Фильтр: <code>{filt_raw}</code></p>
        <p>Получателей: {len(targets)}</p>
        <p>Доставлено: {sent}</p>
        <p>Ошибок: {failed}</p>
        <p><a href='/admin/ui'>Вернуться в админку</a></p>
        """,
        status_code=200,
    )


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
