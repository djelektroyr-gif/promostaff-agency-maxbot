"""Клиентские ERP-экраны MAX: команда, приглашения, смены, назначение (паритет с TG client_company_flows)."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

import visit_card
from config import CONTACT_TELEGRAM, PRIVACY_POLICY_URL
from max_attachments import cb_btn, inline_keyboard
from funnel_db import (
    assign_worker_client_pool_max,
    client_owns_shift_max,
    count_company_members_max,
    create_company_invite_max,
    create_project_for_company_max,
    get_client_company_id_max,
    is_max_visit_client_verified,
    list_projects_for_company_max,
    create_shift_for_company_max,
    list_client_pool_assignable_max,
    list_company_members_max,
    list_shifts_for_company_max,
    require_company_can_create_project_max,
)

logger = logging.getLogger(__name__)

_PAGE = 8
_INVITE_TTL = 14


def _tg_invite_link(token: str) -> str:
    un = (CONTACT_TELEGRAM or "").strip().lstrip("@")
    if not un:
        return f"start=ci_{token}"
    return f"https://t.me/{un}?start=ci_{token}"


def _client_gate(max_uid: int) -> dict[str, Any] | None:
    if not is_max_visit_client_verified(max_uid):
        return {
            "notification": "Нужна регистрация",
            "text": "Сначала пройдите регистрацию заказчика.",
            "format": "markdown",
            "attachments": visit_card.main_menu_keyboard(),
        }
    company_id = get_client_company_id_max(max_uid)
    if not company_id:
        return {
            "notification": "Нет компании",
            "text": "Компания не привязана. Напишите менеджеру.",
            "format": "markdown",
            "attachments": visit_card.client_registered_main_menu_keyboard(),
        }
    return None


def _team_hub_kb() -> list[dict]:
    return visit_card.client_team_hub_keyboard()


def reply_max_client_company(max_uid: int, payload: str) -> dict[str, Any] | None:
    p = (payload or "").strip()
    if not p:
        return None

    gate = _client_gate(max_uid)
    company_id = get_client_company_id_max(max_uid) if gate is None else None

    if p in ("client_team_staff",) or p.startswith("ctstaff_p_"):
        if gate:
            return gate
        page = 0
        if p.startswith("ctstaff_p_"):
            try:
                page = int(p.replace("ctstaff_p_", ""))
            except ValueError:
                page = 0
        total = count_company_members_max(int(company_id), member_role="staff")
        if total == 0:
            return {
                "notification": " ",
                "text": "*Исполнители*\n\nПока никого нет. Пригласите по ссылке (кнопка в меню команды).",
                "format": "markdown",
                "attachments": _team_hub_kb(),
            }
        pages = max(1, (total + _PAGE - 1) // _PAGE)
        page = max(0, min(page, pages - 1))
        rows = list_company_members_max(int(company_id), member_role="staff", limit=_PAGE, offset=page * _PAGE)
        lines = [f"*Исполнители* (стр. {page + 1}/{pages})\n"]
        kb_rows: list[list[dict]] = []
        for r in rows:
            lines.append(f"• {r['full_name'] or r['tg_id']} · {r['profession'] or '—'}")
            kb_rows.append([cb_btn(f"📇 {(r['full_name'] or r['tg_id'])[:20]}", f"max_cwcard_{r['tg_id']}")])
        nav: list[dict] = []
        if page > 0:
            nav.append(cb_btn("◀️", f"ctstaff_p_{page - 1}"))
        if page < pages - 1:
            nav.append(cb_btn("▶️", f"ctstaff_p_{page + 1}"))
        if nav:
            kb_rows.append(nav)
        kb_rows.append([cb_btn("🔙 К команде", "client_team_hub")])
        return {
            "notification": " ",
            "text": "\n".join(lines)[:3900],
            "format": "markdown",
            "attachments": inline_keyboard(kb_rows),
        }

    if p in ("client_team_coordinators",) or p.startswith("ctcoord_p_"):
        if gate:
            return gate
        page = 0
        if p.startswith("ctcoord_p_"):
            try:
                page = int(p.replace("ctcoord_p_", ""))
            except ValueError:
                page = 0
        total = count_company_members_max(int(company_id), member_role="coordinator")
        if total == 0:
            return {
                "notification": " ",
                "text": "*Координаторы*\n\nПока никого нет.",
                "format": "markdown",
                "attachments": _team_hub_kb(),
            }
        pages = max(1, (total + _PAGE - 1) // _PAGE)
        page = max(0, min(page, pages - 1))
        rows = list_company_members_max(int(company_id), member_role="coordinator", limit=_PAGE, offset=page * _PAGE)
        lines = [f"*Координаторы* (стр. {page + 1}/{pages})\n"]
        kb_rows = []
        for r in rows:
            lines.append(f"• {r['full_name'] or r['tg_id']}")
            kb_rows.append([cb_btn(f"📇 {(r['full_name'] or r['tg_id'])[:20]}", f"max_cccard_{r['tg_id']}")])
        nav = []
        if page > 0:
            nav.append(cb_btn("◀️", f"ctcoord_p_{page - 1}"))
        if page < pages - 1:
            nav.append(cb_btn("▶️", f"ctcoord_p_{page + 1}"))
        if nav:
            kb_rows.append(nav)
        kb_rows.append([cb_btn("🔙 К команде", "client_team_hub")])
        return {
            "notification": " ",
            "text": "\n".join(lines)[:3900],
            "format": "markdown",
            "attachments": inline_keyboard(kb_rows),
        }

    if p == "client_invite_staff":
        if gate:
            return gate
        token = create_company_invite_max(
            company_id=int(company_id),
            invite_kind="staff",
            created_by_max_uid=max_uid,
            ttl_days=_INVITE_TTL,
        )
        link = _tg_invite_link(token)
        return {
            "notification": "Ссылка готова",
            "text": (
                "*Приглашение персонала*\n\n"
                "Скопируйте ссылку и отправьте исполнителю в Telegram "
                "(регистрация и согласие — в боте агентства):\n\n"
                f"{link}"
            ),
            "format": "markdown",
            "attachments": _team_hub_kb(),
        }

    if p == "client_invite_coordinator":
        if gate:
            return gate
        token = create_company_invite_max(
            company_id=int(company_id),
            invite_kind="coordinator",
            created_by_max_uid=max_uid,
            ttl_days=_INVITE_TTL,
        )
        link = _tg_invite_link(token)
        return {
            "notification": "Ссылка готова",
            "text": (
                "*Приглашение координатора*\n\n"
                f"{link}\n\n"
                "_Регистрация координатора проходит в Telegram-боте агентства._"
            ),
            "format": "markdown",
            "attachments": _team_hub_kb(),
        }

    if p == "client_project_create":
        if gate:
            return gate
        import visit_flows

        visit_flows.SESSIONS[max_uid] = {
            "flow": "client_company",
            "step": "project_name",
            "data": {"company_id": int(company_id)},
        }
        return {
            "notification": " ",
            "text": "*Создание проекта*\n\nВведите название проекта (не менее 2 символов):",
            "format": "markdown",
            "attachments": inline_keyboard([[cb_btn("🔙 Отмена", "client_projects_hub")]]),
        }

    if p == "client_create_shift":
        if gate:
            return gate
        prows = list_projects_for_company_max(int(company_id), limit=12)
        if not prows:
            return {
                "notification": " ",
                "text": "Сначала создайте проект.",
                "format": "markdown",
                "attachments": visit_card.client_projects_hub_keyboard(),
            }
        kb = [
            [cb_btn(f"{r.get('name', '')[:22]} (#{r.get('id')})", f"max_cshift_proj_{r.get('id')}")]
            for r in prows
        ]
        kb.append([cb_btn("🔙 Отмена", "client_projects_hub")])
        return {
            "notification": " ",
            "text": "*Организовать смену*\n\nВыберите проект:",
            "format": "markdown",
            "attachments": inline_keyboard(kb),
        }

    if p.startswith("max_cshift_proj_"):
        if gate:
            return gate
        pid = int(p.replace("max_cshift_proj_", ""))
        import visit_flows

        visit_flows.SESSIONS[max_uid] = {
            "flow": "client_company",
            "step": "shift_date",
            "data": {"company_id": int(company_id), "project_id": pid},
        }
        return {
            "notification": " ",
            "text": f"*Проект #{pid}*\n\nДата смены `ДД.ММ.ГГГГ`:",
            "format": "markdown",
            "attachments": inline_keyboard([[cb_btn("🔙 Отмена", "client_projects_hub")]]),
        }

    if p == "client_assign_shift" or p.startswith("caslp_"):
        if gate:
            return gate
        page = 0
        if p.startswith("caslp_"):
            try:
                page = int(p.replace("caslp_", ""))
            except ValueError:
                page = 0
        rows, total = list_shifts_for_company_max(int(company_id), limit=_PAGE, offset=page * _PAGE)
        if not rows:
            return {
                "notification": " ",
                "text": "*Назначение*\n\nНет смен. Создайте смену в «Проекты».",
                "format": "markdown",
                "attachments": visit_card.client_projects_hub_keyboard(),
            }
        pages = max(1, (total + _PAGE - 1) // _PAGE)
        kb = [[cb_btn(f"#{r['id']} {r['project_name'][:16]}", f"max_caspick_{r['id']}")] for r in rows]
        nav = []
        if page > 0:
            nav.append(cb_btn("◀️", f"caslp_{page - 1}"))
        if page < pages - 1:
            nav.append(cb_btn("▶️", f"caslp_{page + 1}"))
        if nav:
            kb.append(nav)
        kb.append([cb_btn("🔙 К проектам", "client_projects_hub")])
        return {
            "notification": " ",
            "text": f"*Выберите смену* (стр. {page + 1}/{pages})",
            "format": "markdown",
            "attachments": inline_keyboard(kb),
        }

    if p.startswith("max_caspick_") or p.startswith("caswp_"):
        if gate:
            return gate
        page = 0
        if p.startswith("caswp_"):
            m = re.match(r"^caswp_(\d+)_(\d+)$", p)
            if not m:
                return None
            shift_id, page = int(m.group(1)), int(m.group(2))
        else:
            shift_id = int(p.replace("max_caspick_", ""))
        workers, total = list_client_pool_assignable_max(int(company_id), shift_id, limit=_PAGE, offset=page * _PAGE)
        if not workers:
            return {
                "notification": " ",
                "text": f"*Смена #{shift_id}*\n\nНет свободных исполнителей в команде.",
                "format": "markdown",
                "attachments": inline_keyboard(
                    [
                        [cb_btn("👷 Пригласить", "client_invite_staff")],
                        [cb_btn("🔙 К сменам", "client_assign_shift")],
                    ]
                ),
            }
        pages = max(1, (total + _PAGE - 1) // _PAGE)
        kb = [
            [cb_btn(f"{w['full_name'][:18] or w['tg_id']}", f"casdo_{shift_id}_{w['tg_id']}")]
            for w in workers
        ]
        nav = []
        if page > 0:
            nav.append(cb_btn("◀️", f"caswp_{shift_id}_{page - 1}"))
        if page < pages - 1:
            nav.append(cb_btn("▶️", f"caswp_{shift_id}_{page + 1}"))
        if nav:
            kb.append(nav)
        kb.append([cb_btn("🔙 К сменам", "client_assign_shift")])
        return {
            "notification": " ",
            "text": f"*Смена #{shift_id}* — выберите исполнителя:",
            "format": "markdown",
            "attachments": inline_keyboard(kb),
        }

    if p.startswith("casdo_"):
        if gate:
            return gate
        m = re.match(r"^casdo_(\d+)_(\d+)$", p)
        if not m:
            return None
        shift_id, wid = int(m.group(1)), int(m.group(2))
        ok, msg = assign_worker_client_pool_max(shift_id, wid, int(company_id))
        if not ok:
            return {
                "notification": msg[:80],
                "text": f"❌ {msg}",
                "format": "markdown",
                "attachments": visit_card.client_projects_hub_keyboard(),
            }
        return {
            "notification": "Назначено",
            "text": f"✅ {msg}\nИсполнитель `{wid}` → смена #{shift_id}.",
            "format": "markdown",
            "attachments": inline_keyboard(
                [
                    [cb_btn("👥 Ещё назначение", "client_assign_shift")],
                    [cb_btn("🔙 К проектам", "client_projects_hub")],
                ]
            ),
        }

    if p.startswith("proj_coord_invite_"):
        if gate:
            return gate
        raw = p.replace("proj_coord_invite_", "")
        if not raw.isdigit():
            return None
        pid = int(raw)
        token = create_company_invite_max(
            company_id=int(company_id),
            invite_kind="coordinator",
            created_by_max_uid=max_uid,
            project_id=pid,
            ttl_days=_INVITE_TTL,
        )
        return {
            "notification": "Ссылка",
            "text": f"*Координатор на проект #{pid}*\n\n{_tg_invite_link(token)}",
            "format": "markdown",
            "attachments": inline_keyboard([[cb_btn("🔙 К проектам", "client_projects_hub")]]),
        }

    return None


def process_client_company_session_text(max_uid: int, text: str, session: dict[str, Any]) -> dict[str, Any] | None:
    """Текстовые шаги FSM client_company в MAX."""
    if session.get("flow") != "client_company":
        return None
    step = session.get("step")
    data = session.get("data") if isinstance(session.get("data"), dict) else {}
    company_id = int(data.get("company_id") or 0)
    import visit_flows

    if step == "project_name":
        name = (text or "").strip()
        if len(name) < 2:
            return {
                "notification": "Коротко",
                "text": "Название слишком короткое. Введите ещё раз:",
                "format": "markdown",
            }
        try:
            require_company_can_create_project_max(company_id)
            pid = create_project_for_company_max(company_id, name)
        except ValueError as e:
            visit_flows.clear_session(max_uid)
            return {
                "notification": "Лимит",
                "text": f"❌ {e}",
                "format": "markdown",
                "attachments": visit_card.client_projects_hub_keyboard(),
            }
        except Exception:
            logger.exception("max create project")
            visit_flows.clear_session(max_uid)
            return {
                "notification": "Ошибка",
                "text": "Не удалось создать проект.",
                "format": "markdown",
                "attachments": visit_card.client_projects_hub_keyboard(),
            }
        visit_flows.clear_session(max_uid)
        return {
            "notification": "Создано",
            "text": f"✅ Проект *{name}* (#{pid}) создан.",
            "format": "markdown",
            "attachments": visit_card.client_projects_hub_keyboard(),
        }

    if step == "shift_date":
        data["shift_date"] = text.strip()
        session["step"] = "shift_start"
        session["data"] = data
        visit_flows.SESSIONS[max_uid] = session
        return {"notification": " ", "text": "Время начала `ЧЧ:ММ`:", "format": "markdown"}

    if step == "shift_start":
        if not re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", text.strip()):
            return {"notification": " ", "text": "❌ Формат `10:00`", "format": "markdown"}
        data["start_time"] = text.strip()
        session["step"] = "shift_end"
        session["data"] = data
        visit_flows.SESSIONS[max_uid] = session
        return {"notification": " ", "text": "Время окончания `ЧЧ:ММ`:", "format": "markdown"}

    if step == "shift_end":
        if not re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", text.strip()):
            return {"notification": " ", "text": "❌ Формат `18:00`", "format": "markdown"}
        data["end_time"] = text.strip()
        session["step"] = "shift_location"
        session["data"] = data
        visit_flows.SESSIONS[max_uid] = session
        return {"notification": " ", "text": "Адрес смены:", "format": "markdown"}

    if step == "shift_location":
        loc = text.strip()
        if len(loc) < 5:
            return {"notification": " ", "text": "❌ Слишком короткий адрес", "format": "markdown"}
        data["location"] = loc
        session["step"] = "shift_rate"
        session["data"] = data
        visit_flows.SESSIONS[max_uid] = session
        return {
            "notification": " ",
            "text": "Ставка руб/ч (число). Координатор может уточнить при назначении:",
            "format": "markdown",
        }

    if step == "shift_rate":
        if not text.strip().isdigit():
            return {"notification": " ", "text": "❌ Введите число", "format": "markdown"}
        data["rate"] = int(text.strip())
        project_id = int(data.get("project_id") or 0)
        if not project_id:
            visit_flows.clear_session(max_uid)
            return {
                "notification": " ",
                "text": "Сессия сброшена. Начните снова.",
                "format": "markdown",
                "attachments": visit_card.client_projects_hub_keyboard(),
            }
        try:
            shift_id = create_shift_for_company_max(
                project_id,
                {
                    "date": data.get("shift_date"),
                    "start_time": data.get("start_time"),
                    "end_time": data.get("end_time"),
                    "location": data.get("location"),
                    "rate": data.get("rate"),
                },
            )
        except Exception as e:
            logger.exception("max client shift")
            visit_flows.clear_session(max_uid)
            return {
                "notification": "Ошибка",
                "text": f"❌ {e}",
                "format": "markdown",
                "attachments": visit_card.client_projects_hub_keyboard(),
            }
        visit_flows.clear_session(max_uid)
        return {
            "notification": "Смена создана",
            "text": f"✅ Смена #{shift_id} создана.\nНазначьте исполнителя из команды.",
            "format": "markdown",
            "attachments": inline_keyboard(
                [
                    [cb_btn("👥 Назначить", f"max_caspick_{shift_id}")],
                    [cb_btn("🔙 К проектам", "client_projects_hub")],
                ]
            ),
        }

    return None
