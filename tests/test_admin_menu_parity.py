from __future__ import annotations

import asyncio
from datetime import datetime

import visit_card
import visit_flows


def test_admin_hub_keyboard_has_tg_like_hubs():
    kb = visit_card.admin_agency_hub_keyboard()
    flat = str(kb)
    assert "admin_hub_ops" in flat
    assert "admin_hub_hrm" in flat
    assert "admin_hub_crm" in flat
    assert "admin_hub_system" in flat


def test_admin_system_hub_has_subscriptions_expiring_button():
    kb = visit_card.admin_hub_system_keyboard()
    assert "admin_sys_subscriptions_expiring" in str(kb)


def test_admin_hrm_hub_has_workers_button():
    kb = visit_card.admin_hub_hrm_keyboard()
    assert "admin_hrm_workers" in str(kb)
    assert "admin_hrm_worker_find" in str(kb)
    assert "admin_hrm_payments_export" in str(kb)


def test_registered_menu_admin_hub_requires_admin(monkeypatch):
    monkeypatch.setattr(visit_flows, "ADMIN_MAX_USER_IDS", [])
    reply = visit_flows.registered_menu_static_reply(123456, "admin_agency_hub")
    assert reply is not None
    assert "доступен только администраторам" in str(reply.get("text", "")).lower()


def test_registered_menu_admin_crm_hub_for_admin(monkeypatch):
    monkeypatch.setattr(visit_flows, "ADMIN_MAX_USER_IDS", [42])
    reply = visit_flows.registered_menu_static_reply(42, "admin_hub_crm")
    assert reply is not None
    assert "admin_orders_funnel" in str(reply.get("attachments"))


def test_admin_ops_shifts_list_is_native(monkeypatch):
    monkeypatch.setattr(visit_flows, "ADMIN_MAX_USER_IDS", [42])
    monkeypatch.setattr(
        visit_flows,
        "list_open_shifts_admin_max",
        lambda limit=20: [
            {
                "id": 101,
                "shift_date": "2026-05-21",
                "start_time": "10:00",
                "end_time": "22:00",
                "project_name": "Expo",
                "status": "open",
                "workers_needed": 2,
                "assignments_total": 0,
            }
        ],
    )
    reply = visit_flows.registered_menu_static_reply(42, "admin_ops_shifts_active")
    assert reply is not None
    assert "admin_ops_shift_detail_101" in str(reply.get("attachments"))
    assert "люди: 0/2" in str(reply.get("text", ""))


def test_admin_ops_shift_detail_has_assign_and_report_buttons(monkeypatch):
    monkeypatch.setattr(visit_flows, "ADMIN_MAX_USER_IDS", [42])
    monkeypatch.setattr(
        visit_flows,
        "get_shift_admin_max",
        lambda sid: {
            "id": sid,
            "project_name": "Expo",
            "shift_date": "2026-05-22",
            "start_time": "10:00",
            "end_time": "18:00",
            "location": "ВДНХ",
            "rate": 900,
            "workers_needed": 2,
            "assignments_total": 1,
            "status": "open",
        },
    )
    monkeypatch.setattr(
        visit_flows,
        "list_shift_assignments_for_shift_max",
        lambda sid, limit=120: [
            {"status": "assigned", "worker_name": "Иванов", "last_action_source": "tg"},
            {"status": "confirmed", "worker_name": "Петров"},
            {"status": "checked_in", "worker_name": "Сидоров", "last_action_source": "max"},
            {"status": "checked_out", "worker_name": "Смирнов"},
        ],
    )
    reply = visit_flows.registered_menu_static_reply(42, "admin_ops_shift_detail_101")
    assert reply is not None
    att = str(reply.get("attachments", ""))
    assert "admin_ops_shift_assign_pick_101" in att
    assert "admin_ops_shift_report_101" in att
    assert "admin_ops_shift_risk_unconfirmed_101" in att
    assert "admin_ops_shift_ping_unconfirmed_101" in att
    assert "assigned 1" in str(reply.get("text", ""))
    assert "Иванов" in str(reply.get("text", ""))
    assert "src:TG" in str(reply.get("text", ""))
    assert "src:MAX" in str(reply.get("text", ""))


def test_admin_ops_shift_ping_unconfirmed_no_risk(monkeypatch):
    monkeypatch.setattr(visit_flows, "ADMIN_MAX_USER_IDS", [42])
    monkeypatch.setattr(visit_flows, "get_shift_admin_max", lambda sid: {"id": sid, "project_name": "Expo", "shift_date": "2026-05-22", "start_time": "10:00", "end_time": "18:00"})
    monkeypatch.setattr(visit_flows, "list_shift_assignments_for_shift_max", lambda sid, limit=120: [])
    out = visit_flows.registered_menu_static_reply(42, "admin_ops_shift_ping_unconfirmed_101")
    assert out is not None
    assert "не требуется" in str(out.get("text", "")).lower()


def test_admin_ops_shift_ping_unconfirmed_outside_critical_window(monkeypatch):
    monkeypatch.setattr(visit_flows, "ADMIN_MAX_USER_IDS", [42])
    monkeypatch.setattr(
        visit_flows,
        "get_shift_admin_max",
        lambda sid: {
            "id": sid,
            "project_name": "Expo",
            "shift_date": "2099-05-22",
            "start_time": "10:00:00",
            "end_time": "18:00:00",
        },
    )
    monkeypatch.setattr(
        visit_flows,
        "list_shift_assignments_for_shift_max",
        lambda sid, limit=120: [{"status": "assigned", "worker_name": "Иванов", "worker_tg_id": 123}],
    )
    out = visit_flows.registered_menu_static_reply(42, "admin_ops_shift_ping_unconfirmed_101")
    assert out is not None
    assert "вне критичного окна" in str(out.get("text", "")).lower()


def test_admin_ops_shift_assign_pick_lists_workers(monkeypatch):
    monkeypatch.setattr(visit_flows, "ADMIN_MAX_USER_IDS", [42])
    monkeypatch.setattr(visit_flows, "get_shift_admin_max", lambda sid: {"id": sid})
    monkeypatch.setattr(
        visit_flows,
        "list_assignable_workers_for_shift_max",
        lambda sid, limit=20: [{"user_id": 555, "full_name": "Петров Петр", "profession": "Хелпер"}],
    )
    reply = visit_flows.registered_menu_static_reply(42, "admin_ops_shift_assign_pick_101")
    assert reply is not None
    assert "admin_ops_shift_assign_do_101_555" in str(reply.get("attachments", ""))


def test_admin_ops_shift_report_contains_assignments(monkeypatch):
    monkeypatch.setattr(visit_flows, "ADMIN_MAX_USER_IDS", [42])
    monkeypatch.setattr(
        visit_flows,
        "get_shift_admin_max",
        lambda sid: {
            "id": sid,
            "project_name": "Expo",
            "shift_date": "2026-05-22",
            "start_time": "10:00",
            "end_time": "18:00",
        },
    )
    monkeypatch.setattr(
        visit_flows,
        "list_shift_assignments_for_shift_max",
        lambda sid, limit=120: [
            {
                "worker_name": "Иванов",
                "status": "assigned",
                "checkin_time": None,
                "checkout_time": None,
                "worked_minutes": 0,
            }
        ],
    )
    reply = visit_flows.registered_menu_static_reply(42, "admin_ops_shift_report_101")
    assert reply is not None
    assert "Отчёт по смене #101" in str(reply.get("text", ""))
    assert "Иванов" in str(reply.get("text", ""))


def test_admin_hrm_payments_list_has_items(monkeypatch):
    monkeypatch.setattr(visit_flows, "ADMIN_MAX_USER_IDS", [42])
    monkeypatch.setattr(
        visit_flows,
        "list_worker_payments_recent_max",
        lambda limit=20: [
            {
                "id": 7,
                "worker_tg_id": 123,
                "amount_rub": 9000,
                "status": "pending",
                "title": "Смена 20.05",
                "worker_name": "Иванов Иван",
            }
        ],
    )
    reply = visit_flows.registered_menu_static_reply(42, "admin_hrm_payments")
    assert reply is not None
    assert "admin_hrm_payment_7" in str(reply.get("attachments"))


def test_admin_hrm_payments_export_preview(monkeypatch):
    monkeypatch.setattr(visit_flows, "ADMIN_MAX_USER_IDS", [42])
    monkeypatch.setattr(
        visit_flows,
        "list_worker_payments_recent_max",
        lambda limit=120: [
            {
                "id": 1,
                "worker_tg_id": 111,
                "worker_name": "Иванов",
                "amount_rub": 1234.5,
                "currency": "RUB",
                "status": "pending",
                "title": "Смена",
                "shift_id": 9,
                "created_at": "2026-05-21",
                "paid_at": None,
            }
        ],
    )
    reply = visit_flows.registered_menu_static_reply(42, "admin_hrm_payments_export")
    assert reply is not None
    assert "csv" in str(reply.get("text", "")).lower()


def test_admin_hrm_worker_find_and_detail(monkeypatch):
    monkeypatch.setattr(visit_flows, "ADMIN_MAX_USER_IDS", [42])
    start = visit_flows.registered_menu_static_reply(42, "admin_hrm_worker_find")
    assert start is not None
    assert "найти исполнителя" in str(start.get("text", "")).lower()
    monkeypatch.setattr(
        visit_flows,
        "get_worker_admin_max",
        lambda wid: {
            "user_id": 555,
            "full_name": "Петров Петр",
            "phone": "+79991234567",
            "profession": "Хелпер",
            "status": "approved",
            "cooperation_mode": "agency",
            "rating": 4.5,
        },
    )
    monkeypatch.setattr(
        visit_flows, "get_worker_assignment_stats_max", lambda wid: {"assignments_total": 2, "open_tasks": 1}
    )
    monkeypatch.setattr(
        visit_flows,
        "list_worker_payments_for_worker_max",
        lambda wid, limit=5: [{"id": 11, "amount_rub": 5000, "status": "paid", "title": "Смена"}],
    )
    out = visit_flows.registered_menu_static_reply(42, "admin_hrm_worker_detail_555")
    assert out is not None
    assert "Исполнитель 555" in str(out.get("text", ""))


def test_admin_sys_monitor_contains_subscription_metrics(monkeypatch):
    monkeypatch.setattr(visit_flows, "ADMIN_MAX_USER_IDS", [42])
    monkeypatch.setattr(visit_flows, "get_visitcard_stats", lambda: {"orders": 1, "join": 2, "questions": 3})
    monkeypatch.setattr(
        visit_flows,
        "get_worker_cooperation_mode_metrics",
        lambda: {"agency_workers": 4, "platform_workers": 5},
    )
    monkeypatch.setattr(
        visit_flows,
        "get_users_phone_duplicates_metrics",
        lambda limit=5: {"duplicate_phones_total": 6},
    )
    monkeypatch.setattr(
        visit_flows,
        "get_company_subscription_metrics_max",
        lambda days=7: {"active_total": 7, "expiring_soon": 8, "expired_total": 9, "without_subscription": 10},
    )
    reply = visit_flows.registered_menu_static_reply(42, "admin_sys_monitor")
    assert reply is not None
    text = str(reply.get("text", ""))
    assert "Подписки компаний" in text
    assert "Истекают 7 дней: 8" in text


def test_admin_ops_hub_contains_runtime_shift_counters(monkeypatch):
    monkeypatch.setattr(visit_flows, "ADMIN_MAX_USER_IDS", [42])
    monkeypatch.setattr(
        visit_flows,
        "get_admin_hub_counters_max",
        lambda: {
            "open_shifts": 3,
            "projects_total": 4,
            "checked_in_now": 5,
            "on_break_now": 2,
            "payments_pending": 1,
            "crm_all": 7,
            "crm_kp": 0,
            "crm_urgent": 0,
            "workers_total": 9,
        },
    )
    reply = visit_flows.registered_menu_static_reply(42, "admin_hub_ops")
    assert reply is not None
    text = str(reply.get("text", ""))
    assert "Сейчас на смене: 5" in text
    assert "Сейчас на перерыве: 2" in text


def test_admin_system_hub_contains_runtime_shift_counters(monkeypatch):
    monkeypatch.setattr(visit_flows, "ADMIN_MAX_USER_IDS", [42])
    monkeypatch.setattr(
        visit_flows,
        "get_admin_hub_counters_max",
        lambda: {
            "open_shifts": 3,
            "projects_total": 4,
            "checked_in_now": 5,
            "on_break_now": 2,
            "payments_pending": 1,
            "crm_all": 7,
            "crm_kp": 0,
            "crm_urgent": 0,
            "workers_total": 9,
        },
    )
    reply = visit_flows.registered_menu_static_reply(42, "admin_hub_system")
    assert reply is not None
    text = str(reply.get("text", ""))
    assert "Сейчас на смене: 5" in text
    assert "Сейчас на перерыве: 2" in text


def test_admin_sys_subscriptions_expiring_list(monkeypatch):
    monkeypatch.setattr(visit_flows, "ADMIN_MAX_USER_IDS", [42])
    monkeypatch.setattr(
        visit_flows,
        "list_expiring_company_subscriptions_max",
        lambda days=7, limit=30: [
            {
                "company_id": 101,
                "company_name": "ООО Тест",
                "plan_code": "base",
                "projects_limit": 3,
                "projects_used": 2,
                "ends_at": "2026-05-30 10:00:00",
            }
        ],
    )
    reply = visit_flows.registered_menu_static_reply(42, "admin_sys_subscriptions_expiring")
    assert reply is not None
    text = str(reply.get("text", ""))
    assert "ООО Тест" in text
    assert "проекты: 2/3" in text


def test_admin_sys_subscriptions_expired_filter(monkeypatch):
    monkeypatch.setattr(visit_flows, "ADMIN_MAX_USER_IDS", [42])
    monkeypatch.setattr(
        visit_flows,
        "list_expired_company_subscriptions_max",
        lambda limit=30: [{"company_id": 301, "company_name": "ООО Просрочка", "projects_used": 1, "projects_limit": 1, "plan_code": "base", "ends_at": "2026-05-01"}],
    )
    reply = visit_flows.registered_menu_static_reply(42, "admin_sys_subs_mode_expired")
    assert reply is not None
    assert "только истекшие" in str(reply.get("text", "")).lower()
    assert "ООО Просрочка" in str(reply.get("text", ""))


def test_admin_sys_subscriptions_action_extend(monkeypatch):
    monkeypatch.setattr(visit_flows, "ADMIN_MAX_USER_IDS", [42])
    monkeypatch.setattr(visit_flows, "admin_extend_company_subscription_days_max", lambda cid, days=30: True)
    monkeypatch.setattr(
        visit_flows,
        "get_company_subscription_max",
        lambda cid: {"plan_code": "base", "status": "active", "starts_at": "2026-01-01", "ends_at": "2026-06-01", "projects_limit": 3},
    )
    monkeypatch.setattr(visit_flows, "count_projects_for_company_max", lambda cid: 2)
    monkeypatch.setattr(visit_flows, "log_admin_action_max", lambda *args, **kwargs: None)
    reply = visit_flows.registered_menu_static_reply(42, "admin_sys_subs_act_301_extend_expiring")
    assert reply is not None
    assert str(reply.get("notification", "")).lower() == "обновлено"
    assert "Подписка компании #301" in str(reply.get("text", ""))


def test_admin_sys_subscriptions_company_card_uses_confirm_step(monkeypatch):
    monkeypatch.setattr(visit_flows, "ADMIN_MAX_USER_IDS", [42])
    monkeypatch.setattr(
        visit_flows,
        "get_company_subscription_max",
        lambda cid: {"plan_code": "base", "status": "active", "starts_at": "2026-01-01", "ends_at": "2026-06-01", "projects_limit": 3},
    )
    monkeypatch.setattr(visit_flows, "count_projects_for_company_max", lambda cid: 2)
    reply = visit_flows.registered_menu_static_reply(42, "admin_sys_subs_company_301_expiring")
    assert reply is not None
    assert "admin_sys_subs_confirm_301_extend_expiring" in str(reply.get("attachments"))


def test_admin_sys_subscriptions_confirm_screen(monkeypatch):
    monkeypatch.setattr(visit_flows, "ADMIN_MAX_USER_IDS", [42])
    reply = visit_flows.registered_menu_static_reply(42, "admin_sys_subs_confirm_301_grace_expiring")
    assert reply is not None
    assert "Подтвердите действие" in str(reply.get("text", ""))
    assert "admin_sys_subs_act_301_grace_expiring" in str(reply.get("attachments"))


def test_worker_shifts_menu_renders_assigned_shift(monkeypatch):
    import funnel_db

    monkeypatch.setattr(funnel_db, "has_max_active_executor_profile", lambda uid: True)
    monkeypatch.setattr(funnel_db, "get_max_worker_cooperation_mode", lambda uid: "agency")
    monkeypatch.setattr(funnel_db, "is_max_visit_worker_verified", lambda uid: True)
    monkeypatch.setattr(visit_flows, "resolve_tg_id_for_max_user", lambda uid: 555)
    monkeypatch.setattr(
        visit_flows,
        "list_worker_shifts_max",
        lambda worker_tg_id, limit=20: [
            {
                "shift_id": 77,
                "shift_date": "2026-05-21",
                "start_time": "10:00",
                "end_time": "20:00",
                "project_name": "Expo",
                "assignment_status": "assigned",
            }
        ],
    )
    out = visit_flows.registered_menu_static_reply(42, "worker_reg_shifts")
    assert out is not None
    assert "Мои смены" in str(out.get("text", ""))
    assert "worker_shift_77" in str(out.get("attachments", ""))


def test_worker_shift_card_contains_actions(monkeypatch):
    import funnel_db

    monkeypatch.setattr(funnel_db, "has_max_active_executor_profile", lambda uid: True)
    monkeypatch.setattr(funnel_db, "get_max_worker_cooperation_mode", lambda uid: "agency")
    monkeypatch.setattr(funnel_db, "is_max_visit_worker_verified", lambda uid: True)
    monkeypatch.setattr(visit_flows, "resolve_tg_id_for_max_user", lambda uid: 555)
    monkeypatch.setattr(visit_flows, "auto_close_expired_breaks_max", lambda: 0)
    monkeypatch.setattr(
        visit_flows,
        "get_worker_shift_assignment_max",
        lambda sid, wid: {
            "shift_id": 77,
            "shift_date": "2026-05-21",
            "start_time": "10:00",
            "end_time": "20:00",
            "project_name": "Expo",
            "assignment_status": "confirmed",
            "worked_minutes": 0,
        },
    )
    monkeypatch.setattr(visit_flows, "get_active_break_max", lambda sid, wid: None)
    monkeypatch.setattr(visit_flows, "get_worker_break_stats_max", lambda sid, wid: {"lunch_count": 0, "smoke_count": 0, "tech_count": 0})
    out = visit_flows.registered_menu_static_reply(42, "worker_shift_77")
    assert out is not None
    assert "Смена #77" in str(out.get("text", ""))
    assert "worker_shift_checkin_77" in str(out.get("attachments", ""))


def test_worker_checkin_starts_geo_photo_flow(monkeypatch):
    import funnel_db

    monkeypatch.setattr(funnel_db, "has_max_active_executor_profile", lambda uid: True)
    monkeypatch.setattr(funnel_db, "get_max_worker_cooperation_mode", lambda uid: "agency")
    monkeypatch.setattr(funnel_db, "is_max_visit_worker_verified", lambda uid: True)
    monkeypatch.setattr(visit_flows, "resolve_tg_id_for_max_user", lambda uid: 555)
    monkeypatch.setattr(
        visit_flows,
        "get_worker_shift_assignment_max",
        lambda sid, wid: {"shift_id": 77, "assignment_status": "confirmed"},
    )
    out = visit_flows.registered_menu_static_reply(42, "worker_shift_checkin_77")
    assert out is not None
    assert "Шаг 1/2" in str(out.get("text", ""))
    sess = visit_flows.SESSIONS.get(42) or {}
    assert sess.get("flow") == "worker_shift"
    assert sess.get("step") == "checkin_geo"


def test_worker_checkin_geo_then_photo_completes(monkeypatch):
    visit_flows.SESSIONS[42] = {"flow": "worker_shift", "step": "checkin_geo", "data": {"shift_id": 77}}
    monkeypatch.setattr(visit_flows, "resolve_tg_id_for_max_user", lambda uid: 555)
    monkeypatch.setattr(visit_flows, "registered_menu_static_reply", lambda uid, payload: {"text": "ok", "payload": payload})
    monkeypatch.setattr(
        visit_flows,
        "checkin_worker_shift_max",
        lambda sid, wid, photo_url=None, checkin_location=None: True,
    )

    geo_reply = asyncio.run(
        visit_flows.process_text(
            42,
            "",
            {},
            {"location": {"latitude": 55.75, "longitude": 37.61}},
        )
    )
    assert geo_reply is not None
    assert "Шаг 2/2" in str(geo_reply.get("text", ""))
    assert (visit_flows.SESSIONS.get(42) or {}).get("step") == "checkin_photo"

    done_reply = asyncio.run(
        visit_flows.process_text(
            42,
            "",
            {},
            {"attachments": [{"type": "photo", "payload": {"url": "https://example/photo.jpg"}}]},
        )
    )
    assert done_reply is not None
    assert done_reply.get("payload") == "worker_shift_77"


def test_worker_break_lunch_limit_enforced(monkeypatch):
    import funnel_db

    monkeypatch.setattr(funnel_db, "has_max_active_executor_profile", lambda uid: True)
    monkeypatch.setattr(funnel_db, "get_max_worker_cooperation_mode", lambda uid: "agency")
    monkeypatch.setattr(funnel_db, "is_max_visit_worker_verified", lambda uid: True)
    monkeypatch.setattr(visit_flows, "resolve_tg_id_for_max_user", lambda uid: 555)
    monkeypatch.setattr(
        visit_flows,
        "get_worker_shift_assignment_max",
        lambda sid, wid: {
            "shift_id": sid,
            "shift_date": "2026-05-21",
            "start_time": "09:00:00",
            "end_time": "18:00:00",
            "assignment_status": "checked_in",
            "checkin_time": "2026-05-21 10:00:00",
        },
    )
    monkeypatch.setattr(visit_flows, "get_worker_break_stats_max", lambda sid, wid: {"lunch_count": 1, "smoke_count": 0, "tech_count": 0})
    monkeypatch.setattr(visit_flows, "start_worker_break_max", lambda sid, wid, bt: True)
    out = visit_flows.registered_menu_static_reply(42, "worker_break_start_77_lunch")
    assert out is not None
    assert "только один раз" in str(out.get("text", "")).lower()


def test_ops_shift_risk_lines_max_flags_unconfirmed_close_to_start():
    card = {
        "shift_date": "2026-05-21",
        "start_time": "10:00:00",
        "end_time": "18:00:00",
        "workers_needed": 3,
    }
    counts = {"assigned": 2, "confirmed": 0, "checked_in": 0, "checked_out": 0, "cancelled": 0, "other": 0}
    risks = visit_flows._ops_shift_risk_lines_max(card, counts, now=datetime(2026, 5, 21, 9, 20, 0))
    assert risks
    assert "без подтверждения" in " ".join(risks)
