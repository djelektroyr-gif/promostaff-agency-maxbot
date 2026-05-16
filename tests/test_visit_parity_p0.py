"""P0 паритет визитки MAX ↔ Telegram (unit, без БД)."""
from __future__ import annotations

import visit_card
from funnel_db import worker_tg_id_for_max


def test_worker_tg_id_synthetic_range():
    assert worker_tg_id_for_max(42) == 10**15 + 42


def test_vacancies_list_has_apply_entry_points():
    kb = visit_card.vacancies_list_keyboard()
    flat = str(kb)
    assert "vac_view_helper" in flat
    assert "vac_view_supervisor" in flat


def test_vacancy_detail_has_apply_button():
    kb = visit_card.vacancy_detail_keyboard("promoter")
    assert "vac_apply_promoter" in str(kb)


def test_worker_pending_keyboard_minimal():
    kb = visit_card.worker_pending_verification_keyboard()
    assert "contact_manager" in str(kb)
    assert "main_menu" not in str(kb)


def test_snils_validator():
    import visit_join_validators as v

    assert v.validate_join_snils("112-233-445 95") is True
    assert v.validate_join_snils("000-000-000 00") is False


def test_join_portfolio_menu_keyboard():
    kb = visit_card.join_portfolio_menu_keyboard()
    assert "join_portfolio_none" in str(kb)
    assert "join_portfolio_pdf" in str(kb)
