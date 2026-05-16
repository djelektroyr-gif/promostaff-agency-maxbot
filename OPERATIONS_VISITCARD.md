# PROMOSTAFF Agency MAX Visitcard - Operations

## Admin access

- JSON: `/admin`
- Web UI: `/admin/ui`
- CSV export endpoint:
  - `/admin/export?kind=orders|join|questions`
  - Optional filters:
    - `date_from=YYYY-MM-DD`
    - `date_to=YYYY-MM-DD`

Examples:
- `/admin/export?kind=orders`
- `/admin/export?kind=join&date_from=2026-04-01&date_to=2026-04-15`

## Production (Timeweb)

| | |
|---|---|
| Приложение | `PROMOSTAFF AGENCY MAX BOT` |
| Домен (канон, 2026-05) | `https://djelektroyr-gif-promostaff-agency-maxbot-d923.twc1.net` |
| Статус | Webhook на **d923**, бот отвечает на Старт (подписка перепривязана с ошибочного `…-e4a0…` / старых доменов) |
| Health | `GET …/health` |
| Webhook endpoint | `POST …/webhook` |
| Подписка MAX API | `POST https://platform-api.max.ru/subscriptions` → `url` = webhook выше (см. `promostaff-bot/docs/MAX_WEBHOOK_AND_SUBSCRIPTIONS.md`) |

Переменные в панели (имена): `MAX_TOKEN`, `DATABASE_URL`, `TBANK_LK_URL`, `ADMIN_MAX_USER_IDS`, `WEBSITE_URL`, `PRIVACY_POLICY_URL`, `PYTHONUNBUFFERED` (+ `AGENCY_FEE_PERCENT` в панели, в коде maxbot не используется).

Паритет с Telegram (визитка, до ERP): **`docs/MAX_VISIT_TELEGRAM_PARITY_INVENTORY.md`**.

## Environment

Required:
- `MAX_TOKEN`

Recommended:
- `DATABASE_URL` (stores visitcard leads + funnel tables)
- `BRAND_LOGO_URL` (logo URL shown in welcome text)
- `ADMIN_MAX_USER_IDS` (admin notifications)
- `SMTP_*`, `NOTIFY_EMAIL_TO` (email notifications)

## PostgreSQL tables

- `agency_max_funnel`
- `agency_visit_orders`
- `agency_visit_join_requests`
- `agency_visit_questions`

## Pre-launch checklist

1. `/health` returns `ok: true`.
2. Webhook receives updates without errors.
3. Main menu and all callback flows work.
4. Order flow confirms with estimate and manager disclaimer.
5. Join flow requires selfie and submits.
6. `/admin` metrics include visitcard counters.
7. `/admin/ui` filters show lead rows by kind/date.
8. `/admin/export` returns valid CSV files.

## Deferred item

- Channel subscription verification in MAX is **not configured** yet.
- Status: deferred by decision, return later when platform/API constraints are finalized.
