"""Заявки заказчика только после admin-verify (паритет Telegram)."""
from unittest.mock import patch

import visit_flows as vf


def test_gate_blocks_unverified_registered():
    with patch.object(vf, "has_max_active_executor_profile", return_value=False):
        with patch.object(vf, "is_max_visit_client_verified", return_value=False):
            with patch.object(vf, "is_max_visit_client_registered", return_value=True):
                out = vf._gate_client_quote_access(42)
    assert out is not None
    assert "проверке" in out["text"].lower()


def test_gate_allows_verified():
    with patch.object(vf, "has_max_active_executor_profile", return_value=False):
        with patch.object(vf, "is_max_visit_client_verified", return_value=True):
            assert vf._gate_client_quote_access(42) is None


def test_listing_blocked_for_guest():
    with patch.object(vf, "_gate_client_quote_access") as gate:
        gate.return_value = {"text": "block", "format": "markdown", "attachments": []}
        out = vf.start_listing_order(1)
    assert out["text"] == "block"
