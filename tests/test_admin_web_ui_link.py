from __future__ import annotations

from unittest.mock import patch

import visit_flows as vf


def test_admin_sys_web_admin_returns_ready_link_for_admin():
    with patch.object(vf, "_is_admin_max_uid", return_value=True), patch(
        "admin_web_login_link.build_admin_ui_login_url",
        return_value=("https://max.example.com/admin/ui?token=abc", None),
    ):
        out = vf.registered_menu_static_reply(101, "admin_sys_web_admin")
    assert out is not None
    assert "web admin max" in (out.get("text") or "").lower()
    attachments = out.get("attachments") or []
    assert attachments and attachments[0].get("type") == "inline_keyboard"
    first_row = attachments[0]["payload"]["buttons"][0]
    assert first_row[0]["type"] == "link"
    assert "/admin/ui?token=abc" in first_row[0]["url"]


def test_admin_sys_web_admin_shows_error_if_link_unavailable():
    with patch.object(vf, "_is_admin_max_uid", return_value=True), patch(
        "admin_web_login_link.build_admin_ui_login_url",
        return_value=(None, "не задан ADMIN_UI_TOKEN"),
    ):
        out = vf.registered_menu_static_reply(101, "admin_sys_web_admin")
    assert out is not None
    assert "не задан admin_ui_token" in (out.get("text") or "").lower()
