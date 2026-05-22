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
    monkeypatch.setattr(visit_flows, "resolve_tg_id_for_max_user", lambda _uid: 10000001234001)

    def _fake_notify_registration(subject, plain, client_tg_id):
        notify_calls["subject"] = subject
        notify_calls["plain"] = plain
        notify_calls["client_tg_id"] = client_tg_id

    monkeypatch.setattr(visit_flows, "_schedule_notify_registration", _fake_notify_registration)
    out = asyncio.run(visit_flows.process_callback(max_uid, "confirm_client_visit_yes", {"username": "integrity"}))
    assert out is not None
    assert "Регистрация принята" in str(out.get("text") or "")
    assert save_calls.get("uid") == max_uid
    assert "ООО Интегритет" in str(save_calls.get("data"))
    assert "регистрация заказчика" in str(notify_calls.get("subject") or "").lower()
    assert notify_calls.get("client_tg_id") == 10000001234001
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


def test_cp_submit_does_not_fake_success_when_db_save_failed(monkeypatch):
    max_uid = 992004
    visit_flows.SESSIONS[max_uid] = {
        "flow": "order",
        "step": "cp_confirm",
        "data": {
            "order_consent_accepted": True,
            "event_type": "Дегустация",
            "city": "Москва",
            "event_date": "01.06.2026",
        },
    }

    monkeypatch.setattr(visit_flows, "_gate_client_quote_access", lambda *_a, **_k: None)
    monkeypatch.setattr(visit_flows, "_order_contact_ready", lambda *_a, **_k: True)
    monkeypatch.setattr(visit_flows, "save_visit_order_payload", lambda *_a, **_k: (None, "OFFLINE"))
    monkeypatch.setattr(
        visit_flows,
        "_schedule_notify",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("notify should not be called")),
    )

    out = asyncio.run(visit_flows.process_callback(max_uid, "confirm_cp_order", {"username": "client_u"}))
    assert out is not None
    assert "не удалось сохранить заявку на кп" in str(out.get("text") or "").lower()
    assert max_uid in visit_flows.SESSIONS


def test_listing_submit_does_not_fake_success_when_db_save_failed(monkeypatch):
    max_uid = 992005
    visit_flows.SESSIONS[max_uid] = {
        "flow": "order",
        "step": "listing_confirm",
        "data": {
            "order_consent_accepted": True,
            "listing_role": "Промоутер",
            "listing_description": "Работа на промо-стойке в ТЦ, полный день",
            "contact_name": "Иван",
            "contact_channel": "phone",
            "phone": "+79990000055",
        },
    }

    monkeypatch.setattr(visit_flows, "_gate_client_quote_access", lambda *_a, **_k: None)
    monkeypatch.setattr(visit_flows, "_order_contact_ready", lambda *_a, **_k: True)
    monkeypatch.setattr(visit_flows, "save_visit_order_payload", lambda *_a, **_k: (None, "OFFLINE"))
    monkeypatch.setattr(
        visit_flows,
        "_schedule_notify",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("notify should not be called")),
    )

    out = asyncio.run(
        visit_flows.process_callback(max_uid, "confirm_listing_order", {"username": "client_u"})
    )
    assert out is not None
    assert "не удалось сохранить заявку на объявление" in str(out.get("text") or "").lower()
    assert max_uid in visit_flows.SESSIONS


def test_question_submit_does_not_fake_success_when_db_save_failed(monkeypatch):
    max_uid = 992006
    visit_flows.SESSIONS[max_uid] = {
        "flow": "question",
        "step": "text",
        "data": {"question_consent_accepted": True},
    }

    monkeypatch.setattr(visit_flows, "save_visit_question", lambda *_a, **_k: None)
    monkeypatch.setattr(
        visit_flows,
        "_schedule_notify",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("notify should not be called")),
    )

    out = asyncio.run(
        visit_flows.process_text(max_uid, "Подскажите по ставкам", {"username": "client_u"})
    )
    assert out is not None
    assert "не удалось отправить сообщение менеджеру" in str(out.get("text") or "").lower()
    assert max_uid in visit_flows.SESSIONS
