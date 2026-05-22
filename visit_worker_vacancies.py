"""Доска вакансий верифицированного исполнителя — зеркало handlers/visit_public.py (worker_vacancies*)."""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

import visit_card
from funnel_db import (
    get_vacancy_campaign,
    list_open_vacancy_campaigns,
    list_user_vacancy_responses_current,
    list_user_vacancy_responses_past,
    resolve_tg_id_for_max_user,
    vacancy_campaign_add_response,
    vacancy_campaign_response_count,
)
from max_attachments import cb_btn, inline_keyboard
from max_vacancy_rules import vacancy_rating_gate_for_response
from visit_join_anketa_catalog import (
    PROFESSION_SLUG_TO_TITLE,
    classify_open_vacancy_position_to_slug,
    visit_vacancy_display_rows,
)

_VAC_CAM_STATUS_RU: dict[str, str] = {
    "open": "открыт набор",
    "filled": "набор завершён",
    "closed": "закрыто",
}

_WV_TAB_KEYS = frozenset({"all", "cur", "past"})
_VCBD_LEGACY_RE = re.compile(r"^vcbd_(\d+)$")
_VCBD_TAB_RE = re.compile(r"^vcbd_([acp])_(\d+)$")


def parse_vacancy_board_detail_callback(payload: str) -> tuple[int, str] | None:
    raw = (payload or "").strip()
    m = _VCBD_LEGACY_RE.fullmatch(raw)
    if m:
        return int(m.group(1)), "all"
    m = _VCBD_TAB_RE.fullmatch(raw)
    if not m:
        return None
    code = m.group(1)
    ctx = {"a": "all", "c": "cur", "p": "past"}.get(code)
    if not ctx:
        return None
    return int(m.group(2)), ctx


def _open_vacancy_counts_by_slug(open_campaigns: list[dict]) -> dict[str, int]:
    c: Counter[str] = Counter()
    for camp in open_campaigns:
        slug = classify_open_vacancy_position_to_slug(str(camp.get("position") or ""))
        if slug:
            c[slug] += 1
    return dict(c)


def _wv_tab_button_label(active: str, tab_key: str, title: str) -> str:
    return f"✓ {title}" if active == tab_key else title


def _tabs_row(active: str) -> list[dict]:
    return [
        cb_btn(_wv_tab_button_label(active, "cur", "Текущие"), "wvtab_cur"),
        cb_btn(_wv_tab_button_label(active, "past", "Прошедшие"), "wvtab_past"),
        cb_btn(_wv_tab_button_label(active, "all", "Все"), "wvtab_all"),
    ]


def _vacancy_campaign_detail_plain(camp: dict, *, response_count: int) -> str:
    cid = int(camp.get("id") or 0)
    lines: list[str] = [f"Объявление #{cid}", ""]
    for label, key in (
        ("Должность", "position"),
        ("Город", "city"),
        ("Адрес / локация", "address"),
    ):
        val = (camp.get(key) or "").strip()
        if val:
            lines.append(f"{label}: {val}")
    sd = (camp.get("shift_date") or "").strip()
    st = (camp.get("shift_time") or "").strip()
    if sd or st:
        lines.append(f"Дата и время: {sd}" + (f", {st}" if st else ""))
    pay = (camp.get("pay") or "").strip()
    if pay:
        lines.append(f"Оплата: {pay}")
    tasks = (camp.get("tasks") or "").strip()
    if tasks:
        lines.append(f"Задачи: {tasks}")
    try:
        mr = float(camp.get("min_rating") or 0.0)
        if mr > 0:
            lines.append(f"Мин. рейтинг для рассылки: {mr:.1f}")
    except (TypeError, ValueError):
        pass
    st_l = str(camp.get("status") or "").strip().lower()
    lines.append("")
    lines.append(f"Статус: {_VAC_CAM_STATUS_RU.get(st_l, st_l or '—')}")
    needed = int(camp.get("slots_needed") or 0)
    if needed > 0:
        lines.append(f"Откликов: {int(response_count)} из {needed}")
    payload = (camp.get("payload") or "").strip()
    if payload:
        lines.extend(["", "Текст объявления:", payload])
    return "\n".join(lines).strip()


def _hub_text_all(open_campaigns: list[dict]) -> str:
    lines: list[str] = [
        "Вакансии · Все",
        "",
        "Открытые объявления (как в рассылке) и направления каталога со счётчиком открытых объявлений по роли.",
        "",
        "— Открытые объявления —",
    ]
    if not open_campaigns:
        lines.append("Пока нет открытых объявлений. Когда появятся — они будут здесь и придут в личные сообщения.")
    else:
        for c in open_campaigns:
            cid = int(c["id"])
            pos = (c.get("position") or "").strip() or "—"
            city = (c.get("city") or "").strip()
            st_l = str(c.get("status") or "").strip().lower()
            st_ru = _VAC_CAM_STATUS_RU.get(st_l, st_l or "—")
            tail = pos + (f", {city}" if city else "")
            cnt = int(c.get("response_count") or 0)
            need = int(c.get("slots_needed") or 0)
            lines.append(f"• #{cid} {tail} — {st_ru}")
            if need > 0:
                lines.append(f"  откликов: {cnt}/{need}")
    lines.extend(["", "— Направления (счётчики по открытым объявлениям) —", "Нажмите роль ниже, чтобы увидеть объявления по направлению."])
    return "\n".join(lines)


def _hub_text_current(rows: list[dict]) -> str:
    lines: list[str] = ["Вакансии · Текущие", "", "Отклики на открытые и заполненные кампании.", ""]
    if not rows:
        lines.append("Пока пусто.")
    else:
        for c in rows:
            cid = int(c["id"])
            pos = (c.get("position") or "").strip() or "—"
            st_l = str(c.get("status") or "").strip().lower()
            st_ru = _VAC_CAM_STATUS_RU.get(st_l, st_l or "—")
            lines.append(f"• #{cid} {pos} — {st_ru}")
    return "\n".join(lines)


def _hub_text_past(rows: list[dict]) -> str:
    lines: list[str] = [
        "Вакансии · Прошедшие",
        "",
        "Кампании, на которые вы откликнулись, со статусом «закрыто».",
        "",
    ]
    if not rows:
        lines.append("Пока пусто.")
    else:
        for c in rows:
            cid = int(c["id"])
            pos = (c.get("position") or "").strip() or "—"
            st_l = str(c.get("status") or "").strip().lower()
            st_ru = _VAC_CAM_STATUS_RU.get(st_l, st_l or "—")
            lines.append(f"• #{cid} {pos} — {st_ru}")
    return "\n".join(lines)


def _hub_keyboard_all(active_tab: str, open_campaigns: list[dict], slug_counts: dict[str, int]) -> list[dict]:
    rows: list[list[dict]] = [_tabs_row(active_tab)]
    for c in open_campaigns[:14]:
        cid = int(c["id"])
        pos = ((c.get("position") or "").strip() or "вакансия")[:22]
        city = ((c.get("city") or "").strip())[:14]
        label = f"📣 #{cid} {pos}"
        if city:
            label += f" · {city}"
        if len(label) > 62:
            label = label[:59] + "…"
        rows.append([cb_btn(label, f"vcbd_a_{cid}")])
    vac_rows = list(visit_vacancy_display_rows())
    for i in range(0, len(vac_rows), 2):
        chunk = vac_rows[i : i + 2]
        row_btns: list[dict] = []
        for slug, em_title, _desc in chunk:
            n = int(slug_counts.get(slug) or 0)
            row_btns.append(cb_btn(f"{em_title} ({n})", f"wvf:{slug}"))
        rows.append(row_btns)
    rows.append([cb_btn("📚 Справочник профессий (текстом)", "worker_vac_cat")])
    rows.append([cb_btn("🏠 Главное меню", "main_menu")])
    return inline_keyboard(rows)


def _hub_keyboard_list(active_tab: str, campaigns: list[dict], data_prefix: str) -> list[dict]:
    rows: list[list[dict]] = [_tabs_row(active_tab)]
    for c in campaigns[:20]:
        cid = int(c["id"])
        pos = ((c.get("position") or "").strip() or "вакансия")[:22]
        city = ((c.get("city") or "").strip())[:14]
        label = f"📣 #{cid} {pos}"
        if city:
            label += f" · {city}"
        if len(label) > 62:
            label = label[:59] + "…"
        rows.append([cb_btn(label, f"vcbd_{data_prefix}_{cid}")])
    rows.append([cb_btn("🏠 Главное меню", "main_menu")])
    return inline_keyboard(rows)


def worker_vacancies_hub_screen(max_uid: int, tab: str) -> dict[str, Any]:
    tg_id = resolve_tg_id_for_max_user(int(max_uid))
    t = tab if tab in _WV_TAB_KEYS else "all"
    if t == "all":
        open_c = list_open_vacancy_campaigns(28)
        counts = _open_vacancy_counts_by_slug(open_c)
        return {
            "text": _hub_text_all(open_c),
            "format": None,
            "attachments": _hub_keyboard_all("all", open_c, counts),
        }
    if t == "cur":
        cur = list_user_vacancy_responses_current(tg_id, 40)
        return {
            "text": _hub_text_current(cur),
            "format": None,
            "attachments": _hub_keyboard_list("cur", cur, "c"),
        }
    past = list_user_vacancy_responses_past(tg_id, 40)
    return {
        "text": _hub_text_past(past),
        "format": None,
        "attachments": _hub_keyboard_list("past", past, "p"),
    }


def worker_vacancies_catalog_screen() -> dict[str, Any]:
    lines = ["*Открытые вакансии*\n"]
    for _k, title, desc in visit_vacancy_display_rows():
        lines.append(f"*{title}*\n{desc}\n")
    return {
        "text": "\n".join(lines).strip(),
        "format": "markdown",
        "attachments": inline_keyboard(
            [
                [cb_btn("🔙 К разделу «Все»", "wvtab_all")],
                [cb_btn("🏠 Главное меню", "main_menu")],
            ]
        ),
    }


def worker_vacancies_by_slug_screen(max_uid: int, slug: str) -> dict[str, Any]:
    open_c = list_open_vacancy_campaigns(80)
    filtered = [
        c
        for c in open_c
        if classify_open_vacancy_position_to_slug(str(c.get("position") or "")) == slug
    ]
    title_ru = (PROFESSION_SLUG_TO_TITLE.get(slug) or slug).strip()
    lines: list[str] = [f"Открытые объявления · {title_ru}", ""]
    if not filtered:
        lines.append("Сейчас нет открытых объявлений с этой ролью в каталоге.")
    else:
        for c in filtered[:40]:
            cid = int(c["id"])
            pos = (c.get("position") or "").strip() or "—"
            city = (c.get("city") or "").strip()
            tail = pos + (f", {city}" if city else "")
            lines.append(f"• #{cid} {tail}")
    rows: list[list[dict]] = []
    for c in filtered[:14]:
        cid = int(c["id"])
        pos = ((c.get("position") or "").strip() or "вакансия")[:22]
        city = ((c.get("city") or "").strip())[:14]
        label = f"📣 #{cid} {pos}"
        if city:
            label += f" · {city}"
        if len(label) > 62:
            label = label[:59] + "…"
        rows.append([cb_btn(label, f"vcbd_a_{cid}")])
    rows.append([cb_btn("🔙 К разделу «Все»", "wvtab_all")])
    rows.append([cb_btn("🏠 Главное меню", "main_menu")])
    return {"text": "\n".join(lines).strip(), "format": None, "attachments": inline_keyboard(rows)}


def worker_vacancy_detail_screen(max_uid: int, payload: str) -> dict[str, Any] | None:
    parsed = parse_vacancy_board_detail_callback(payload)
    if not parsed:
        return None
    cid, tab_ctx = parsed
    camp = get_vacancy_campaign(cid)
    if not camp:
        return {
            "notification": "Не найдено",
            "text": "Объявление не найдено или уже недоступно.",
            "format": None,
            "attachments": visit_card.worker_registered_main_menu_keyboard(),
        }
    tg_id = resolve_tg_id_for_max_user(int(max_uid))
    cnt = vacancy_campaign_response_count(cid)
    text = _vacancy_campaign_detail_plain(camp, response_count=cnt)
    gate = vacancy_rating_gate_for_response(tg_id, camp)
    try:
        need_r = float(camp.get("min_rating") or 0.0)
    except (TypeError, ValueError):
        need_r = 0.0
    if not gate.get("allowed") and need_r > 1e-9:
        text += (
            f"\n\nНужен рейтинг не ниже {float(gate.get('min_rating') or 0.0):.1f} "
            "по этой профессии (с учётом вашей анкеты и тегов)."
        )
    needed = int(camp.get("slots_needed") or 0)
    status_l = str(camp.get("status") or "").strip().lower()
    rows: list[list[dict]] = []
    can_reply = status_l == "open" and needed > 0 and bool(gate.get("allowed"))
    if can_reply:
        rows.append([cb_btn("✅ Откликнуться", f"vy:{cid}")])
    back_cb = {"all": "wvtab_all", "cur": "wvtab_cur", "past": "wvtab_past"}.get(tab_ctx, "wvtab_all")
    rows.append([cb_btn("🔙 Назад", back_cb)])
    rows.append([cb_btn("🏠 Главное меню", "main_menu")])
    return {"text": text, "format": None, "attachments": inline_keyboard(rows)}


def worker_vacancy_apply(max_uid: int, campaign_id: int) -> dict[str, Any]:
    tg_id = resolve_tg_id_for_max_user(int(max_uid))
    res = vacancy_campaign_add_response(int(campaign_id), int(tg_id))
    if not res.get("ok"):
        reason = str(res.get("reason") or "")
        if reason == "rating":
            return {
                "notification": "Рейтинг",
                "text": (
                    f"Отклик недоступен: нужен рейтинг от {float(res.get('min_rating') or 0):.1f}, "
                    f"у вас по этой роли — {float(res.get('effective') or 0):.1f}."
                ),
                "format": None,
                "attachments": visit_card.worker_registered_main_menu_keyboard(),
            }
        if reason == "closed":
            return {
                "notification": "Закрыто",
                "text": "Набор по этому объявлению уже закрыт.",
                "format": None,
                "attachments": visit_card.worker_registered_main_menu_keyboard(),
            }
        return {
            "notification": "Ошибка",
            "text": "Не удалось отправить отклик. Попробуйте позже.",
            "format": None,
            "attachments": visit_card.worker_registered_main_menu_keyboard(),
        }
    if res.get("new"):
        note = "Отклик отправлен ✅"
    else:
        note = "Вы уже откликались на это объявление"
    return {
        "notification": note,
        "text": note + ". Менеджер свяжется с вами при отборе.",
        "format": None,
        "attachments": visit_card.worker_registered_main_menu_keyboard(),
    }
