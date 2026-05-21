from __future__ import annotations

import asyncio

import visit_flows


def test_join_button_steps_do_not_send_extra_text_messages():
    uid = 223001
    for step in (
        "anketa_invite",
        "profession_category",
        "profession_summary",
        "portfolio_menu",
        "tax_menu",
        "tax_fl_menu",
        "experience_pick",
        "review_submit",
    ):
        visit_flows.SESSIONS[uid] = {"flow": "join", "step": step, "data": {}}
        out = asyncio.run(visit_flows.process_text(uid, "случайный текст", {}))
        assert out is None, step
    visit_flows.SESSIONS.pop(uid, None)
