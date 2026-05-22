"""Правила отклика на vacancy_campaigns — зеркало services/vacancy_campaign_rules.py (TG)."""
from __future__ import annotations

from funnel_db import get_worker_row_for_tg
from visit_join_anketa_catalog import PROFESSION_SLUG_TO_TITLE, classify_open_vacancy_position_to_slug


def _norm_title(t: str) -> str:
    return (t or "").strip()


def worker_matches_vacancy_profession(tg_user_id: int, position: str) -> bool:
    w = get_worker_row_for_tg(int(tg_user_id))
    if not w:
        return False
    titles = [_norm_title(str(w.get("profession") or ""))]
    pos_l = _norm_title(position).lower()
    if not pos_l:
        return False
    for t in titles:
        tl = t.lower()
        if len(tl) >= 2 and tl in pos_l:
            return True
    slug = classify_open_vacancy_position_to_slug(position)
    if slug:
        canon = (PROFESSION_SLUG_TO_TITLE.get(slug) or "").strip().lower()
        for t in titles:
            tl = t.lower()
            if canon and (canon == tl or canon in tl or tl in canon):
                return True
    return False


def effective_worker_rating_for_vacancy(tg_user_id: int, position: str) -> float:
    w = get_worker_row_for_tg(int(tg_user_id))
    try:
        base = float(w.get("rating") or 0.0) if w else 0.0
    except (TypeError, ValueError):
        base = 0.0
    if worker_matches_vacancy_profession(tg_user_id, position):
        return base
    return 0.0


def vacancy_rating_gate_for_response(tg_user_id: int, camp: dict) -> dict:
    need = float(camp.get("min_rating") or 0.0)
    pos = str(camp.get("position") or "")
    eff = effective_worker_rating_for_vacancy(tg_user_id, pos)
    if need <= 1e-9:
        return {"allowed": True, "min_rating": need, "effective": eff}
    return {"allowed": eff + 1e-9 >= need, "min_rating": need, "effective": eff}
