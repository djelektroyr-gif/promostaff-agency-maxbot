from __future__ import annotations

import handlers
import visit_card as vc
from max_attachments import inline_keyboard


def test_inline_keyboard_empty_returns_no_attachment():
    assert inline_keyboard([]) == []
    assert vc.cp_step_keyboard() == []


def test_sanitize_strips_empty_inline_keyboard():
    body = {
        "text": "Шаг КП",
        "attachments": [{"type": "inline_keyboard", "payload": {"buttons": []}}],
    }
    out = handlers._sanitize_max_outgoing_body(body)
    assert "attachments" not in out
