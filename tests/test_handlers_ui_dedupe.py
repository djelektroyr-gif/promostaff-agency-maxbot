from __future__ import annotations

from unittest.mock import patch

import handlers
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
