from __future__ import annotations

from unittest.mock import patch

import visit_card as vc


def _labels_from_keyboard(kb: list[dict]) -> list[str]:
    if not kb:
        return []
    root = kb[0] if isinstance(kb[0], dict) else {}
    payload = root.get("payload") if isinstance(root, dict) else {}
    rows = payload.get("buttons") if isinstance(payload, dict) else []
    out: list[str] = []
    for row in rows:
        if not row:
            continue
        btn = row[0]
        out.append(str(btn.get("text") or ""))
    return out


def test_admin_main_menu_has_admin_buttons_first_and_no_about():
    with patch.object(vc, "is_admin_user", return_value=True):
        kb = vc.main_menu_keyboard(101)
    labels = _labels_from_keyboard(kb)
    assert labels[:2] == ["🧭 Управление агентством", "🛡 Web admin MAX"]
    assert "📋 О нас" not in labels


def test_non_admin_main_menu_keeps_about_button():
    with patch.object(vc, "is_admin_user", return_value=False):
        kb = vc.main_menu_keyboard(202)
    labels = _labels_from_keyboard(kb)
    assert labels and labels[0] == "📋 О нас"


def test_admin_role_home_shows_web_admin_not_about():
    with patch.object(vc, "is_admin_user", return_value=True):
        out = vc.message_role_home(101)
    attachments = out.get("attachments") or []
    labels = _labels_from_keyboard(attachments)
    assert "🛡 Web admin MAX" in labels
    assert "📋 О нас" not in labels


def test_client_pending_menu_has_manager_and_main():
    kb = vc.client_pre_erp_pending_keyboard()
    labels = _labels_from_keyboard(kb)
    assert labels == ["📞 Связаться с менеджером", "🏠 Главное меню"]


def test_client_verified_menu_tab_bar_and_home_actions():
    kb = vc.client_registered_main_menu_keyboard(quotes_enabled=True)
    flat = str(kb)
    assert "client_applications_hub" in flat
    assert "client_projects_hub" in flat
    assert "client_team_hub" in flat
    assert "client_finance_hub" in flat
    assert "open_web_cabinet" in flat
    assert "contact_manager" in flat


def test_client_registered_menu_has_manager_contact():
    kb = vc.client_registered_main_menu_keyboard(quotes_enabled=True)
    labels = _labels_from_keyboard(kb)
    assert "📞 Связаться с менеджером" in labels


def test_worker_registered_menu_has_manager_contact():
    kb = vc.worker_registered_main_menu_keyboard()
    labels = _labels_from_keyboard(kb)
    assert "📞 Связаться с менеджером" in labels
    assert "📋 Вакансии" in labels
    assert labels.index("📋 Вакансии") < labels.index("💳 Мои выплаты")
