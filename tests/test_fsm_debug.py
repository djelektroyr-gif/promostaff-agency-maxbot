from __future__ import annotations

import visit_flows


def test_debug_session_text_no_session():
    uid = 998001
    visit_flows.SESSIONS.pop(uid, None)
    text = visit_flows.debug_session_text(uid)
    assert "активной сессии нет" in text.lower()


def test_debug_session_text_with_session():
    uid = 998002
    visit_flows.SESSIONS[uid] = {
        "flow": "client_visit",
        "step": "email",
        "data": {"company_name": "ООО Тест", "inn": "7707083893"},
    }
    text = visit_flows.debug_session_text(uid)
    assert "client_visit" in text
    assert "email" in text
    assert "company_name" in text
    visit_flows.SESSIONS.pop(uid, None)
