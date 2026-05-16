"""P1: T-Bank gate, listing, clarification helpers."""
from __future__ import annotations

import visit_card
import visit_flows
from visit_clarification_flows import _patch_from_text, _prompt_ru
from join_clarification_db import CLARIFICATION_FLAG_LABELS_RU, _flag_satisfied


def test_tbank_gate_keyboard_requires_url(monkeypatch):
    monkeypatch.setattr(visit_card, "TBANK_LK_URL", "")
    assert visit_card.tbank_cabinet_gate_keyboard() is None
    monkeypatch.setattr(visit_card, "TBANK_LK_URL", "https://example.test/lk")
    kb = visit_card.tbank_cabinet_gate_keyboard()
    assert kb is not None


def test_join_tbank_gate_skips_without_url():
    s = {"flow": "join", "step": "tax_se_cert", "data": {"tax_cert_ref": "x"}}
    out = visit_flows._join_begin_tbank_gate(s)
    if not (visit_card.TBANK_LK_URL or "").strip():
        assert s["step"] == "snils"
    else:
        assert s["step"] == "tbank_cabinet"
        assert "text" in out


def test_listing_preview_contains_role():
    data = {
        "listing_role": "Промоутер",
        "city": "Москва",
        "listing_description": "Описание тестовое достаточно длинное",
        "event_date": "июнь",
        "contact_name": "Иванов",
        "contact_phone": "+7900",
        "contact_email": "a@b.ru",
        "company_name": "ООО Тест",
        "company_inn": "7707083893",
        "contact_channel": "max_chat",
    }
    txt = visit_flows._listing_preview_text(data)
    assert "Промоутер" in txt
    assert "Москва" in txt


def test_clarification_patch_inn():
    p = _patch_from_text("tx", "770708389301")
    assert p["tax_inn"] == "770708389301"


def test_clarification_flag_satisfied_selfie():
    pl = {"selfie_url": "https://x"}
    assert _flag_satisfied("sf", pl)


def test_clarification_labels_complete():
    assert "pm" in CLARIFICATION_FLAG_LABELS_RU
    assert _prompt_ru("fn")
