from __future__ import annotations

import asyncio

import visit_flows


def test_client_visit_consent_clears_order_tail():
    max_uid = 991001
    visit_flows.SESSIONS[max_uid] = {
        "flow": "client_visit",
        "step": "consent",
        "data": {
            "order_kind": "cp_request",
            "contact_channel": "email",
            "call_time": "будни",
            "canonical_user_tg_id": 12345,
        },
    }
    out = asyncio.run(visit_flows.process_callback(max_uid, "consent_client_visit_accept", {}))
    assert out is not None
    session = visit_flows.SESSIONS[max_uid]
    assert session.get("step") == "company_name"
    data = session.get("data") or {}
    assert data.get("canonical_user_tg_id") == 12345
    assert "order_kind" not in data
    assert "contact_channel" not in data
    assert "call_time" not in data


def test_client_visit_confirm_saves_registration_fields_only(monkeypatch):
    max_uid = 991002
    saved: dict = {}

    visit_flows.SESSIONS[max_uid] = {
        "flow": "client_visit",
        "step": "confirm",
        "data": {
            "company_name": "ООО Тест",
            "contact_name": "Иванов Иван Иванович",
            "position_in_org": "Руководитель отдела",
            "phone": "+79991234567",
            "inn": "7707083893",
            "contact_email": "client@test.ru",
            "canonical_user_tg_id": 777,
            "order_kind": "quick_estimate",
            "contact_channel": "call",
            "cp_contact_channel": "email",
        },
    }

    def _fake_save(uid, username, data):
        saved["uid"] = uid
        saved["username"] = username
        saved["data"] = dict(data)

    monkeypatch.setattr(visit_flows, "save_max_visit_client_verified", _fake_save)
    out = asyncio.run(visit_flows.process_callback(max_uid, "confirm_client_visit_yes", {"username": "tester"}))
    assert out is not None
    assert saved["uid"] == max_uid
    payload = saved["data"]
    assert payload.get("company_name") == "ООО Тест"
    assert payload.get("canonical_user_tg_id") == 777
    assert "order_kind" not in payload
    assert "contact_channel" not in payload
    assert "cp_contact_channel" not in payload
