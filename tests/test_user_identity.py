"""Резолв пользователя по телефону (MAX)."""
from unittest.mock import patch

import user_identity as ui


def test_normalize_phone_ru():
    assert ui.normalize_phone_ru("+7 (916) 123-45-67") == "79161234567"
    assert ui.normalize_phone_ru("89161234567") == "79161234567"
    assert ui.normalize_phone_ru("") == ""


def test_resolve_continue_when_no_rows():
    with patch.object(ui, "find_users_by_phone", return_value=[]):
        with patch("user_identity.worker_tg_id_for_max", return_value=10**15 + 42):
            res = ui.resolve_registration_by_phone(42, "+79161234567", "worker")
    assert res.action == "continue"
    assert res.canonical_tg_id == 10**15 + 42


def test_resolve_role_conflict_client_as_worker():
    row = {"tg_id": 100, "max_user_id": None, "role": "client", "phone": "79161111111"}
    with patch.object(ui, "find_users_by_phone", return_value=[row]):
        with patch.object(ui, "_user_is_client", return_value=True):
            with patch.object(ui, "_user_is_active_worker", return_value=False):
                with patch.object(ui, "link_max_user_id"):
                    res = ui.resolve_registration_by_phone(99, "79161111111", "worker")
    assert res.action == "role_conflict"


def test_resolve_resume_worker_links_max():
    row = {"tg_id": 200, "max_user_id": None, "role": "worker", "phone": "79162222222"}
    with patch.object(ui, "find_users_by_phone", return_value=[row]):
        with patch.object(ui, "_user_is_client", return_value=False):
            with patch.object(ui, "_user_is_active_worker", return_value=True):
                with patch.object(ui, "_user_worker_status", return_value=ui.WORKER_STATUS_APPROVED):
                    with patch.object(ui, "link_max_user_id") as link:
                        res = ui.resolve_registration_by_phone(55, "79162222222", "worker")
    link.assert_called_once_with(200, 55)
    assert res.action == "resume_worker_verified"
    assert res.canonical_tg_id == 200


def test_resolve_collapses_duplicates_then_resumes_worker():
    dup_rows = [
        {"tg_id": 10**15 + 77, "max_user_id": 77, "role": "worker", "phone": "79169999999"},
        {"tg_id": 777001, "max_user_id": None, "role": "worker", "phone": "79169999999"},
    ]
    canonical_row = {"tg_id": 777001, "max_user_id": 77, "role": "worker", "phone": "79169999999"}
    with patch.object(ui, "find_users_by_phone", side_effect=[dup_rows, [canonical_row]]):
        with patch.object(ui, "_collapse_phone_rows_if_safe", return_value=777001):
            with patch.object(ui, "_user_is_client", return_value=False):
                with patch.object(ui, "_user_is_active_worker", return_value=True):
                    with patch.object(ui, "_user_worker_status", return_value=ui.WORKER_STATUS_APPROVED):
                        with patch.object(ui, "link_max_user_id") as link:
                            res = ui.resolve_registration_by_phone(77, "+7 916 999-99-99", "worker")
    link.assert_called_once_with(777001, 77)
    assert res.action == "resume_worker_verified"
    assert res.canonical_tg_id == 777001


def test_resolve_duplicates_with_conflict_stays_ambiguous():
    dup_rows = [
        {"tg_id": 101001, "max_user_id": 12, "role": "worker", "phone": "79160000000"},
        {"tg_id": 101002, "max_user_id": 34, "role": "worker", "phone": "79160000000"},
    ]
    with patch.object(ui, "find_users_by_phone", return_value=dup_rows):
        with patch.object(ui, "_collapse_phone_rows_if_safe", return_value=None):
            res = ui.resolve_registration_by_phone(99, "79160000000", "worker")
    assert res.action == "ambiguous"


def test_collapse_does_not_merge_two_real_tg_ids_without_synthetic():
    rows = [
        {"tg_id": 8545518666, "max_user_id": None, "role": "admin", "phone": "79685337332"},
        {"tg_id": 335505123, "max_user_id": None, "role": "worker", "phone": "79685337332"},
    ]
    with patch.object(ui, "_merge_users_rows") as merge_rows:
        with patch.object(ui, "link_max_user_id") as link:
            collapsed = ui._collapse_phone_rows_if_safe(123, rows)
    assert collapsed is None
    merge_rows.assert_not_called()
    link.assert_not_called()


def test_resolve_ignores_admin_phone_row():
    rows = [
        {"tg_id": 8545518666, "max_user_id": None, "role": "admin", "phone": "79685337332"},
        {"tg_id": 335505123, "max_user_id": None, "role": "worker", "phone": "79685337332"},
    ]
    with patch.object(ui, "find_users_by_phone", return_value=rows):
        with patch.object(ui, "_user_is_client", return_value=False):
            with patch.object(ui, "_user_is_active_worker", return_value=True):
                with patch.object(ui, "_user_worker_status", return_value=ui.WORKER_STATUS_APPROVED):
                    with patch.object(ui, "link_max_user_id") as link:
                        res = ui.resolve_registration_by_phone(500, "+7 968 533 73 32", "worker")
    link.assert_called_once_with(335505123, 500)
    assert res.action == "resume_worker_verified"
    assert res.canonical_tg_id == 335505123
