"""Вход в анкету исполнителя — экраны как в Telegram."""
import asyncio
from unittest.mock import patch

import visit_card
import visit_flows as vf


def test_join_team_intro_keyboard_matches_tg_layout():
    kb = visit_card.join_team_intro_keyboard()
    labels = [row[0]["text"] for row in kb[0]["payload"]["buttons"]]
    assert labels == [
        "📝 Заполнить анкету",
        "📋 Требования к кандидатам",
        "⬅️ Назад",
    ]


def test_show_join_team_blocks_registered_client():
    with patch.object(vf, "_join_entry_blocked", return_value={"text": "block"}):
        out = vf.show_join_team(1)
    assert out["text"] == "block"


def test_show_join_team_starts_role_entry():
    with patch.object(vf, "_join_entry_blocked", return_value=None):
        out = vf.show_join_team(1)
    assert "Уже регистрировался" in out["text"]
    labels = [row[0]["text"] for row in out["attachments"][0]["payload"]["buttons"]]
    assert "✅ Уже регистрировался" in labels


def test_role_entry_keyboard_payloads():
    kb = visit_card.role_entry_keyboard("client")
    buttons = kb[0]["payload"]["buttons"]
    payloads = [buttons[0][0]["payload"], buttons[1][0]["payload"]]
    assert payloads == ["visit_entry_returning:client", "visit_entry_new:client"]


def test_role_not_found_keyboard():
    kb = visit_card.role_not_found_keyboard("client")
    buttons = kb[0]["payload"]["buttons"]
    assert buttons[0][0]["payload"] == "visit_entry_new:client"
    assert buttons[1][0]["payload"] == "visit_entry_returning:client"


def test_join_anketa_invite_keyboard_matches_telegram():
    kb = visit_card.join_anketa_invite_keyboard()
    buttons = kb[0]["payload"]["buttons"]
    assert len(buttons) == 1
    assert buttons[0][0]["text"] == "📝 Заполнить анкету"
    assert buttons[0][0]["payload"] == "join_proceed_anketa"


def test_join_consent_from_profile_goes_direct_to_profession_category():
    uid = 991101
    vf.SESSIONS[uid] = {
        "flow": "join",
        "step": "consent",
        "data": {"join_entry": "profile", "position": "Хостес"},
    }
    out = asyncio.run(vf.process_callback(uid, "consent_join_accept", {}))
    assert out is not None
    assert "ВЫБОР ПРОФЕССИИ" in str(out.get("text") or "")
    session = vf.SESSIONS[uid]
    assert session["step"] == "profession_category"
    assert session["data"].get("join_profession_titles") == []
    assert session["data"].get("position") == ""


def test_join_consent_from_vacancy_goes_to_profession_summary():
    uid = 991102
    vf.SESSIONS[uid] = {
        "flow": "join",
        "step": "consent",
        "data": {"join_entry": "vacancy", "position": "Бариста"},
    }
    out = asyncio.run(vf.process_callback(uid, "consent_join_accept", {}))
    assert out is not None
    assert "ПРОФЕССИИ" in str(out.get("text") or "")
    session = vf.SESSIONS[uid]
    assert session["step"] == "profession_summary"
    assert session["data"].get("join_profession_titles") == ["Бариста"]
