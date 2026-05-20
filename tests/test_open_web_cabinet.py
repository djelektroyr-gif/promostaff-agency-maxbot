from __future__ import annotations

from unittest.mock import patch

import visit_flows as vf


def test_open_web_cabinet_requires_verification():
    with patch("funnel_db.is_max_visit_client_verified", return_value=False), patch(
        "funnel_db.is_max_visit_worker_verified", return_value=False
    ):
        out = vf.registered_menu_static_reply(101, "open_web_cabinet")
    assert out is not None
    assert "верификации" in (out.get("text") or "").lower()


def test_open_web_cabinet_returns_one_time_link():
    with patch("funnel_db.is_max_visit_client_verified", return_value=True), patch(
        "funnel_db.is_max_visit_worker_verified", return_value=False
    ), patch(
        "cabinet_web_login_token.build_cabinet_web_login_url",
        return_value=("https://promostaff.pro/cabinet/enter?token=abc", None),
    ):
        out = vf.registered_menu_static_reply(101, "open_web_cabinet")
    assert out is not None
    assert "кабинет" in (out.get("text") or "").lower()
    attachments = out.get("attachments") or []
    assert attachments and attachments[0].get("type") == "inline_keyboard"
    first_row = attachments[0]["payload"]["buttons"][0]
    assert first_row[0]["type"] == "link"
    assert "cabinet/enter?token=" in first_row[0]["url"]


def test_legacy_client_cabinet_alias_uses_same_flow():
    with patch("funnel_db.is_max_visit_client_verified", return_value=True), patch(
        "funnel_db.is_max_visit_worker_verified", return_value=False
    ), patch(
        "cabinet_web_login_token.build_cabinet_web_login_url",
        return_value=("https://promostaff.pro/cabinet/enter?token=legacy", None),
    ):
        out = vf.registered_menu_static_reply(101, "client_cabinet")
    assert out is not None
    attachments = out.get("attachments") or []
    assert attachments and attachments[0].get("type") == "inline_keyboard"
    first_row = attachments[0]["payload"]["buttons"][0]
    assert "cabinet/enter?token=legacy" in first_row[0]["url"]


def test_open_web_cabinet_error_shows_retry_button():
    with patch("funnel_db.is_max_visit_client_verified", return_value=True), patch(
        "funnel_db.is_max_visit_worker_verified", return_value=False
    ), patch(
        "cabinet_web_login_token.build_cabinet_web_login_url",
        return_value=(None, "Кабинет временно недоступен"),
    ):
        out = vf.registered_menu_static_reply(101, "open_web_cabinet")
    assert out is not None
    assert "временно недоступен" in (out.get("text") or "").lower()
    assert "open_web_cabinet" in str(out.get("attachments"))
