from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import visit_card
import visit_flows


def test_admin_visit_registration_keyboard_has_cvf_cvr():
    kb = visit_card.admin_visit_registration_keyboard(10000001234567)
    flat = str(kb)
    assert "cvf:10000001234567" in flat
    assert "cvr:10000001234567" in flat


def test_admin_cvf_verifies_client(monkeypatch):
    admin_max = 900001
    client_tg = 1000000999001
    calls: dict = {}

    monkeypatch.setattr(visit_card, "is_admin_user", lambda uid: uid == admin_max)
    monkeypatch.setattr(visit_flows, "approve_visit_client_by_tg_id", lambda tid: calls.setdefault("approve", tid))

    async def _fake_notify_menu(tid):
        calls["notify"] = tid

    monkeypatch.setattr(visit_flows, "_notify_max_client_verified_menu", _fake_notify_menu)
    monkeypatch.setattr(visit_flows.asyncio, "create_task", lambda coro: calls.setdefault("notify_task", coro))

    out = visit_flows._admin_client_registration_callback(admin_max, f"cvf:{client_tg}")
    assert out is not None
    assert "верифицирован" in str(out.get("notification") or "").lower()
    assert calls.get("approve") == client_tg


def test_admin_cvr_starts_reject_reason_step(monkeypatch):
    admin_max = 900002
    client_tg = 1000000999002
    monkeypatch.setattr(visit_card, "is_admin_user", lambda uid: uid == admin_max)

    out = visit_flows._admin_client_registration_callback(admin_max, f"cvr:{client_tg}")
    assert out is not None
    sess = visit_flows.SESSIONS[admin_max]
    assert sess.get("flow") == "admin"
    assert sess.get("step") == "client_reg_reject_reason"
    assert sess["data"]["reject_client_tg_id"] == client_tg


def test_registration_notify_passes_keyboard(monkeypatch):
    captured: dict = {}

    async def _fake_notify_agency(subject, plain, *, max_attachments=None):
        captured["subject"] = subject
        captured["plain"] = plain
        captured["attachments"] = max_attachments

    monkeypatch.setattr(visit_flows, "notify_agency_admins", _fake_notify_agency)
    asyncio.run(visit_flows._notify_registration_admins("subj", "body", 42))
    assert captured.get("attachments")
    assert "cvf:42" in str(captured["attachments"])
