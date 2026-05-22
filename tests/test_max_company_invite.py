from __future__ import annotations

import max_company_invite as mci


def test_parse_ci_token_variants():
    assert mci.parse_ci_token("ci_abc123def4567890") == "abc123def4567890"
    assert mci.parse_ci_token("/start ci_abc123def4567890") == "abc123def4567890"
    assert mci.parse_ci_token("https://t.me/bot?start=ci_deadbeefdeadbeef") == "deadbeefdeadbeef"
    assert mci.parse_ci_token("hello") is None


def test_invite_error_used():
    assert mci.invite_error_message({"used_at": "x"}) == "Эта ссылка уже использована."
    assert mci.invite_error_message(None) == "Такого приглашения нет."


def test_invite_share_text_mentions_max_start():
    txt = mci.invite_share_text_max("aabbccdd")
    assert "/start ci_aabbccdd" in txt
    assert "MAX" in txt
