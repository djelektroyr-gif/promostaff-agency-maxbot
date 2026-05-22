from __future__ import annotations

import asyncio

import visit_card
import visit_flows
from visit_join_anketa_catalog import ProfessionCategory, resolve_profession_category_token


def test_profession_categories_keyboard_matches_telegram_two_categories():
    kb = visit_card.profession_categories_keyboard()
    flat = str(kb)
    assert "prof_cat:main" in flat
    assert "prof_cat:creative" in flat
    assert "prof_cat:tech" not in flat
    assert "prof_cat:admin" not in flat
    assert "ProfessionCategory" not in flat


def test_join_prof_cat_accepts_legacy_enum_repr_payload(monkeypatch):
    max_uid = 991101
    visit_flows.SESSIONS[max_uid] = {
        "flow": "join",
        "step": "profession_category",
        "data": {"join_consent_accepted": True},
    }
    out = asyncio.run(
        visit_flows.process_callback(
            max_uid,
            "prof_cat:ProfessionCategory.CREATIVE",
            {},
        )
    )
    assert out is not None
    assert "Выберите профессию" in str(out.get("text") or "")
    assert visit_flows.SESSIONS[max_uid]["data"]["profession_category"] == ProfessionCategory.CREATIVE.value


def test_legacy_tech_category_maps_to_main_catalog():
    assert resolve_profession_category_token("tech") == "main"
    assert resolve_profession_category_token("ProfessionCategory.TECH") == "main"


def test_main_catalog_includes_driver_not_separate_tech_category():
    from visit_join_anketa_catalog import PROFESSION_BY_CATEGORY

    slugs = [slug for _e, _t, slug in PROFESSION_BY_CATEGORY[ProfessionCategory.MAIN]]
    assert "driver" in slugs
    assert "supervisor" in slugs
