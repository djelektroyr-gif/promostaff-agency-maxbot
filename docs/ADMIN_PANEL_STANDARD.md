# PROMOSTAFF Admin Panel Standard

## Purpose
- Unified admin UX across PROMOSTAFF bots (same structure, labels, and actions).
- Fast operational control from one panel (metrics, entities, actions, logs).

## Core Sections
- `Metrics`: workers, clients, projects, open shifts, pending approvals.
- `Workers`: list, filters by status, approve/reject, safe delete.
- `Clients`: list, safe delete with cascade warning.
- `Projects`: create, list, safe delete with cascade.
- `Shifts`: create, assign, close, delete, geo-control settings.
- `Ops`: seed test data, maintenance actions.
- `Audit`: who did what and when.

## UX Rules
- Keep one entrypoint (`/admin` or admin button in bot menu).
- Show key metrics at top (cards or compact list).
- Every destructive action requires explicit confirmation.
- Every operation returns clear result message and next-step button.
- Use consistent callback/route prefixes: `admin_<entity>_<action>`.

## Safety Rules
- Use `*_safe`/`*_cascade` operations explicitly named in code.
- Before delete, show impact preview (affected shifts/tasks/assignments/chat).
- Log all admin actions in audit log with actor, action, entity, details.
- Never hide failed actions; surface readable error text.

## Minimal API Contract
- `GET /admin` -> summary + quick links.
- `GET /admin/<entity>` -> list with filters.
- `POST /admin/<entity>/<action>` -> apply action + log.

## Bot Menu Contract
- Admin main menu must include:
  - Metrics
  - Workers
  - Clients
  - Projects
  - Shifts
  - Audit log
  - Test data generator (for demo/stage)

