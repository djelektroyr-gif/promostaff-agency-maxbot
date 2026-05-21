from __future__ import annotations

from unittest.mock import patch

import handlers
import visit_card
import visit_flows


def test_duplicate_text_reply_detected_on_same_step():
    uid = 123456
    visit_flows.SESSIONS[uid] = {"flow": "join", "step": "full_name", "data": {}}
    reply = {"text": "Укажите ФИО", "format": "markdown"}
    assert handlers._is_duplicate_text_reply(uid, reply) is False
    assert handlers._is_duplicate_text_reply(uid, reply) is True
    visit_flows.SESSIONS.pop(uid, None)


def test_duplicate_text_reply_not_triggered_for_different_steps():
    uid = 123457
    visit_flows.SESSIONS[uid] = {"flow": "join", "step": "full_name", "data": {}}
    reply = {"text": "Укажите ФИО", "format": "markdown"}
    assert handlers._is_duplicate_text_reply(uid, reply) is False
    visit_flows.SESSIONS[uid]["step"] = "phone"
    assert handlers._is_duplicate_text_reply(uid, reply) is False
    visit_flows.SESSIONS.pop(uid, None)


def test_duplicate_text_reply_allowed_after_interval():
    uid = 123458
    visit_flows.SESSIONS[uid] = {"flow": "join", "step": "full_name", "data": {}}
    reply = {"text": "Проверьте поле ФИО", "format": "markdown"}
    with patch("handlers.time.time", return_value=1000.0):
        assert handlers._is_duplicate_text_reply(uid, reply) is False
    with patch("handlers.time.time", return_value=1002.0):
        assert handlers._is_duplicate_text_reply(uid, reply) is True
    with patch("handlers.time.time", return_value=1008.5):
        assert handlers._is_duplicate_text_reply(uid, reply) is False
    visit_flows.SESSIONS.pop(uid, None)


def test_short_notification_from_text_strips_markdown():
    txt = "*Ошибка:* Проверьте ИНН\n\nПодробности ниже."
    note = handlers._short_notification_from_text(txt)
    assert "*" not in note
    assert "Ошибка" in note


def test_strip_registration_escape_keyboard_for_join_step():
    uid = 123499
    visit_flows.SESSIONS[uid] = {"flow": "join", "step": "full_name", "data": {}}
    reply = {
        "text": "Введите ФИО",
        "format": "markdown",
        "attachments": visit_card.back_to_main_keyboard(),
    }
    out = handlers._strip_registration_escape_keyboard(uid, reply)
    assert out.get("attachments") == []
    visit_flows.SESSIONS.pop(uid, None)


def test_keep_non_escape_keyboard_for_join_step():
    uid = 123500
    visit_flows.SESSIONS[uid] = {"flow": "join", "step": "tax_menu", "data": {}}
    reply = {
        "text": "Выберите налоговый статус",
        "format": "markdown",
        "attachments": visit_card.join_tax_status_keyboard(),
    }
    out = handlers._strip_registration_escape_keyboard(uid, reply)
    assert out.get("attachments") is not None
    btns = out["attachments"][0]["payload"]["buttons"]
    payloads = {str(btn.get("payload") or "") for row in btns for btn in row}
    assert "tax_back_bd" in payloads
    assert "main_menu" not in payloads
    visit_flows.SESSIONS.pop(uid, None)


def test_strip_consent_gate_keyboard_after_client_consent_step():
    uid = 123501
    visit_flows.SESSIONS[uid] = {"flow": "client_visit", "step": "company_name", "data": {}}
    reply = {
        "text": "Укажите название юрлица заказчика",
        "format": "markdown",
        "attachments": visit_card.consent_gate_keyboard("client_visit"),
    }
    out = handlers._strip_registration_escape_keyboard(uid, reply)
    assert out.get("attachments") == []
    visit_flows.SESSIONS.pop(uid, None)


def test_join_phone_step_forces_clean_screen_without_inline_keyboard():
    uid = 123502
    visit_flows.SESSIONS[uid] = {"flow": "join", "step": "phone", "data": {}}
    from max_attachments import phone_input_keyboard

    reply = {
        "text": "Укажите номер телефона",
        "format": "markdown",
        "attachments": phone_input_keyboard(),
    }
    out = handlers._strip_registration_escape_keyboard(uid, reply)
    assert out.get("attachments") == []
    visit_flows.SESSIONS.pop(uid, None)


def test_client_phone_step_keeps_phone_keyboard():
    uid = 123503
    visit_flows.SESSIONS[uid] = {"flow": "client_visit", "step": "phone", "data": {}}
    from max_attachments import phone_input_keyboard

    reply = {
        "text": "Введите телефон контактного лица",
        "format": "markdown",
        "attachments": phone_input_keyboard(),
    }
    out = handlers._strip_registration_escape_keyboard(uid, reply)
    assert out.get("attachments") is not None
    visit_flows.SESSIONS.pop(uid, None)
