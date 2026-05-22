from __future__ import annotations

import visit_card as vc
import visit_worker_vacancies as wv


def test_worker_vacancies_flow_payload_recognized():
    assert vc.is_visit_flow_payload("worker_vacancies")
    assert vc.is_visit_flow_payload("wvtab_all")
    assert vc.is_visit_flow_payload("wvf:promoter")
    assert vc.is_visit_flow_payload("vcbd_a_12")
    assert vc.is_visit_flow_payload("vy:99")


def test_worker_vacancies_hub_screen_shape(monkeypatch):
    monkeypatch.setattr(wv, "resolve_tg_id_for_max_user", lambda _u: 1001)
    monkeypatch.setattr(wv, "list_open_vacancy_campaigns", lambda _l: [])
    monkeypatch.setattr(wv, "list_user_vacancy_responses_current", lambda *_a, **_k: [])
    monkeypatch.setattr(wv, "list_user_vacancy_responses_past", lambda *_a, **_k: [])
    out = wv.worker_vacancies_hub_screen(42, "all")
    assert "Вакансии · Все" in str(out.get("text") or "")
    assert "wvtab_cur" in str(out.get("attachments") or "")
