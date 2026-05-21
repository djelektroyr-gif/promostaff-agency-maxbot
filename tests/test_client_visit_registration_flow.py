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
        return True

    monkeypatch.setattr(visit_flows, "save_max_visit_client_verified", _fake_save)
    monkeypatch.setattr(visit_flows, "_schedule_notify", lambda *_args, **_kwargs: None)
    out = asyncio.run(visit_flows.process_callback(max_uid, "confirm_client_visit_yes", {"username": "tester"}))
    assert out is not None
    assert saved["uid"] == max_uid
    payload = saved["data"]
    assert payload.get("company_name") == "ООО Тест"
    assert payload.get("canonical_user_tg_id") == 777
    assert "order_kind" not in payload
    assert "contact_channel" not in payload
    assert "cp_contact_channel" not in payload


def test_client_visit_confirm_notifies_admins(monkeypatch):
    max_uid = 991007
    calls: dict = {}
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
        },
    }

    monkeypatch.setattr(visit_flows, "save_max_visit_client_verified", lambda *_a, **_k: True)

    def _fake_notify(subject, plain):
        calls["subject"] = subject
        calls["plain"] = plain

    monkeypatch.setattr(visit_flows, "_schedule_notify", _fake_notify)
    out = asyncio.run(visit_flows.process_callback(max_uid, "confirm_client_visit_yes", {"username": "tester"}))
    assert out is not None
    assert "Принято" in str(out.get("notification") or "")
    assert "регистрация заказчика" in str(calls.get("subject") or "").lower()
    assert "ООО Тест" in str(calls.get("plain") or "")


def test_client_visit_confirm_does_not_fake_success_when_save_failed(monkeypatch):
    max_uid = 991008
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
        },
    }
    monkeypatch.setattr(visit_flows, "save_max_visit_client_verified", lambda *_a, **_k: False)
    monkeypatch.setattr(visit_flows, "_schedule_notify", lambda *_a, **_k: None)
    out = asyncio.run(visit_flows.process_callback(max_uid, "confirm_client_visit_yes", {"username": "tester"}))
    assert out is not None
    assert "Не удалось сохранить" in str(out.get("text") or "")
    assert max_uid in visit_flows.SESSIONS


def test_client_visit_confirm_edit_opens_field_menu():
    max_uid = 991003
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
        },
    }
    out = asyncio.run(visit_flows.process_callback(max_uid, "confirm_client_visit_edit", {}))
    assert out is not None
    assert "Что хотите исправить?" in str(out.get("text") or "")
    buttons = str(out.get("attachments") or "")
    assert "Юрлицо" in buttons
    assert "Телефон" in buttons
    assert "visitreg_back" in buttons


def test_client_visit_phone_field_edit_returns_to_preview(monkeypatch):
    max_uid = 991004
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
        },
    }

    monkeypatch.setattr(visit_flows, "_phone_resolve_or_none", lambda *_args, **_kwargs: None)
    out_pick = asyncio.run(visit_flows.process_callback(max_uid, "vredit:p", {}))
    assert out_pick is not None
    assert "телефон контактного лица" in str(out_pick.get("text") or "").lower()

    out_save = asyncio.run(visit_flows.process_text(max_uid, "+79990001122", {}))
    assert out_save is not None
    assert "Проверка данных" in str(out_save.get("text") or "")
    assert "+79990001122" in str(out_save.get("text") or "")
    assert visit_flows.SESSIONS[max_uid]["step"] == "confirm"


def test_start_client_visit_menu_skips_consent_when_prior_pd_context(monkeypatch):
    max_uid = 991005
    visit_flows.SESSIONS.pop(max_uid, None)
    monkeypatch.setattr(visit_flows, "has_max_active_executor_profile", lambda _uid: False)
    monkeypatch.setattr(visit_flows, "is_max_visit_client_registered", lambda _uid: False)
    monkeypatch.setattr(visit_flows, "is_max_visit_client_verified", lambda _uid: False)
    monkeypatch.setattr(visit_flows, "user_has_prior_bot_pd_context_max", lambda _uid: True)

    out = visit_flows.start_client_visit_menu(max_uid)
    assert "Давайте познакомимся" in str(out.get("text") or "")
    session = visit_flows.SESSIONS.get(max_uid) or {}
    assert session.get("flow") == "client_visit"
    assert session.get("step") == "company_name"


def test_start_client_visit_menu_shows_role_entry_without_prior_pd_context(monkeypatch):
    max_uid = 991006
    visit_flows.SESSIONS.pop(max_uid, None)
    monkeypatch.setattr(visit_flows, "has_max_active_executor_profile", lambda _uid: False)
    monkeypatch.setattr(visit_flows, "is_max_visit_client_registered", lambda _uid: False)
    monkeypatch.setattr(visit_flows, "is_max_visit_client_verified", lambda _uid: False)
    monkeypatch.setattr(visit_flows, "user_has_prior_bot_pd_context_max", lambda _uid: False)

    out = visit_flows.start_client_visit_menu(max_uid)
    assert "Уже регистрировался" in str(out.get("text") or "")
