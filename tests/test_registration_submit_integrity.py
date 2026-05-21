from __future__ import annotations

import asyncio

import visit_flows


def test_client_submit_requires_db_save_and_notifies(monkeypatch):
    max_uid = 992001
    notify_calls: dict = {}
    save_calls: dict = {}
    visit_flows.SESSIONS[max_uid] = {
        "flow": "client_visit",
        "step": "confirm",
        "data": {
            "company_name": "ООО Интегритет",
            "contact_name": "Петров Петр Петрович",
            "position_in_org": "Директор",
            "phone": "+79990000001",
            "inn": "7707083893",
            "contact_email": "owner@test.ru",
        },
    }

    def _fake_save(uid, username, data):
        save_calls["uid"] = uid
        save_calls["username"] = username
        save_calls["data"] = dict(data)
        return True

    def _fake_notify(subject, plain):
        notify_calls["subject"] = subject
        notify_calls["plain"] = plain

    monkeypatch.setattr(visit_flows, "save_max_visit_client_verified", _fake_save)
    monkeypatch.setattr(visit_flows, "_schedule_notify", _fake_notify)
    out = asyncio.run(visit_flows.process_callback(max_uid, "confirm_client_visit_yes", {"username": "integrity"}))
    assert out is not None
    assert "Регистрация принята" in str(out.get("text") or "")
    assert save_calls.get("uid") == max_uid
    assert "ООО Интегритет" in str(save_calls.get("data"))
    assert "регистрация заказчика" in str(notify_calls.get("subject") or "").lower()
    assert "ООО Интегритет" in str(notify_calls.get("plain") or "")


def test_worker_submit_requires_db_save_and_notifies(monkeypatch):
    max_uid = 992002
    notify_calls: dict = {}
    visit_flows.SESSIONS[max_uid] = {
        "flow": "join",
        "step": "review_submit",
        "data": {
            "join_consent_accepted": True,
            "full_name": "Иванов Иван Иванович",
            "phone": "+79990000002",
            "birth_date": "1990-01-01",
            "position": "Промоутер",
            "profession_category": "promo",
            "tax_status_label": "Самозанятый",
            "tax_inn": "500100732259",
            "contact_email": "worker@test.ru",
            "city": "Москва",
            "metro_station": "Тверская",
        },
    }

    monkeypatch.setattr(visit_flows, "save_visit_join", lambda *_a, **_k: 501)

    def _fake_notify(subject, plain):
        notify_calls["subject"] = subject
        notify_calls["plain"] = plain

    monkeypatch.setattr(visit_flows, "_schedule_notify", _fake_notify)
    out = asyncio.run(visit_flows.process_callback(max_uid, "join_review_ok", {"username": "worker_u"}))
    assert out is not None
    assert "отправлена на проверку" in str(out.get("text") or "").lower()
    assert "заявка в команду" in str(notify_calls.get("subject") or "").lower()
    assert "Иванов Иван Иванович" in str(notify_calls.get("plain") or "")


def test_worker_submit_does_not_fake_success_when_db_save_failed(monkeypatch):
    max_uid = 992003
    visit_flows.SESSIONS[max_uid] = {
        "flow": "join",
        "step": "review_submit",
        "data": {
            "join_consent_accepted": True,
            "full_name": "Сидоров Сидор Сидорович",
            "phone": "+79990000003",
            "birth_date": "1991-02-02",
            "position": "Хелпер",
            "profession_category": "promo",
            "tax_status_label": "Физлицо",
            "city": "Москва",
        },
    }

    monkeypatch.setattr(visit_flows, "save_visit_join", lambda *_a, **_k: None)
    monkeypatch.setattr(visit_flows, "_schedule_notify", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("notify should not be called")))
    out = asyncio.run(visit_flows.process_callback(max_uid, "join_review_ok", {"username": "worker_u"}))
    assert out is not None
    assert "не удалось сохранить анкету" in str(out.get("text") or "").lower()
    assert max_uid in visit_flows.SESSIONS
