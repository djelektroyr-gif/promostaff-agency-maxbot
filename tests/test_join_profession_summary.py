"""Несколько профессий в одной анкете MAX."""
import visit_flows as vf


def test_append_join_profession_titles_dedup():
    data: dict = {}
    raw, ok = vf._append_join_profession_title(data, "Промоутер")
    assert ok and raw == ["Промоутер"]
    _, dup = vf._append_join_profession_title(data, "промоутер")
    assert not dup and len(data["join_profession_titles"]) == 1
    _, ok2 = vf._append_join_profession_title(data, "Хостес")
    assert ok2 and data["position"] == "Промоутер"
    assert data["join_profession_titles"] == ["Промоутер", "Хостес"]
