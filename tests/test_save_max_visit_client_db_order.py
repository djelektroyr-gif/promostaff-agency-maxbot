from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import funnel_db


class _RecordingCursor:
    def __init__(self) -> None:
        self.sql: list[str] = []

    def execute(self, query, params=None):
        self.sql.append(" ".join(str(query).split()))

    def fetchone(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@contextmanager
def _fake_connection():
    cur = _RecordingCursor()
    yield MagicMock(cursor=lambda: cur)


def test_save_max_visit_client_upserts_users_before_visit_clients(monkeypatch):
    monkeypatch.setattr(funnel_db, "DATABASE_URL", "postgresql://test")
    recorded: list[str] = []

    @contextmanager
    def _conn():
        cur = _RecordingCursor()
        yield MagicMock(cursor=lambda: cur)
        recorded.extend(cur.sql)

    monkeypatch.setattr(funnel_db, "connection", _conn)
    monkeypatch.setattr(funnel_db, "_client_tg_id_for_max_cp", lambda *_a, **_k: 10000000000000042)
    monkeypatch.setattr(funnel_db, "_ensure_company_for_max_client", lambda *_a, **_k: 7)

    ok = funnel_db.save_max_visit_client_verified(
        42,
        "tester",
        {
            "company_name": "ООО Тест",
            "contact_name": "Иванов Иван Иванович",
            "position_in_org": "Директор",
            "phone": "+79991234567",
            "inn": "7707083893",
            "contact_email": "client@test.ru",
        },
    )
    assert ok is True
    assert recorded
    users_idx = next(i for i, s in enumerate(recorded) if s.startswith("INSERT INTO users"))
    visit_idx = next(i for i, s in enumerate(recorded) if "INSERT INTO visit_clients" in s)
    clients_idx = next(i for i, s in enumerate(recorded) if "INSERT INTO clients" in s)
    assert users_idx < visit_idx < clients_idx


def test_save_max_visit_client_returns_false_without_database_url(monkeypatch):
    monkeypatch.setattr(funnel_db, "DATABASE_URL", "")
    assert (
        funnel_db.save_max_visit_client_verified(
            1,
            "",
            {"company_name": "X", "contact_name": "A B C", "phone": "+79990000000"},
        )
        is False
    )
