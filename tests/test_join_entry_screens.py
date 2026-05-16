"""Вход в анкету исполнителя — экраны как в Telegram."""
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
