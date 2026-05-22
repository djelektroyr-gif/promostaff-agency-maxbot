from __future__ import annotations

import visit_card
import visit_flows
import funnel_db


def test_visit_payload_registry_has_client_cabinet_slice_actions():
    for payload in (
        "client_project_create",
        "client_create_shift",
        "client_assign_shift",
        "client_team_staff",
        "client_invite_staff",
        "client_reg_subscription",
        "client_reg_team",
        "client_reg_reports",
        "client_applications_hub",
        "client_projects_hub",
        "client_team_hub",
        "client_finance_hub",
    ):
        assert visit_card.is_visit_flow_payload(payload), payload


def test_client_projects_hub_keyboard_contains_actions():
    kb = visit_card.client_projects_hub_keyboard()
    flat = str(kb)
    assert "client_project_create" in flat
    assert "client_create_shift" in flat
    assert "client_assign_shift" in flat
    assert "my_projects" in flat


def test_client_finance_hub_has_subscription_and_reports():
    flat = str(visit_card.client_finance_hub_keyboard())
    assert "client_reg_subscription" in flat
    assert "client_reg_reports" in flat


def test_client_projects_screen_is_no_longer_stub(monkeypatch):
    monkeypatch.setattr(visit_flows, "has_max_active_executor_profile", lambda *_: False)
    monkeypatch.setattr(funnel_db, "is_max_visit_client_registered", lambda *_: True)
    monkeypatch.setattr(funnel_db, "is_max_visit_client_verified", lambda *_: True)
    monkeypatch.setattr(visit_flows, "get_client_company_id_max", lambda *_: 77)
    monkeypatch.setattr(
        visit_flows,
        "list_projects_for_company_max",
        lambda *_args, **_kwargs: [
            {"id": 901, "name": "Event Expo", "status": "planned", "shifts_count": 2},
        ],
    )
    out = visit_flows.registered_menu_static_reply(555, "client_reg_projects")
    assert out is not None
    assert "Event Expo" in str(out.get("text", ""))
    assert "client_project_create" in str(out.get("attachments", ""))
