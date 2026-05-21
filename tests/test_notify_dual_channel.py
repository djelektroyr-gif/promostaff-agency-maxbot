from __future__ import annotations

import asyncio

import notify


def test_notify_agency_admins_reports_tg_and_max_counters(monkeypatch):
    async def _fake_email(_s: str, _b: str) -> bool:
        return True

    async def _fake_max(_t: str) -> int:
        return 2

    async def _fake_tg(_t: str) -> int:
        return 3

    monkeypatch.setattr(notify, "send_admin_email", _fake_email)
    monkeypatch.setattr(notify, "send_admin_max_messages", _fake_max)
    monkeypatch.setattr(notify, "send_admin_telegram_messages", _fake_tg)
    out = asyncio.run(notify.notify_agency_admins("subj", "body"))
    assert out.get("email_sent") is True
    assert out.get("max_messages") == 2
    assert out.get("tg_messages") == 3
