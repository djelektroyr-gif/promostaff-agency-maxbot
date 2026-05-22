"""Приём приглашения ci_ в MAX: согласие ПДн, рассылки, анкета / регистрация координатора."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

import visit_card
import visit_flows
from config import PRIVACY_POLICY_URL
from max_attachments import cb_btn, inline_keyboard, link_btn
from funnel_db import (
    COOPERATION_MODE_CUSTOMER,
    COOPERATION_MODE_PLATFORM,
    COMPANY_MEMBER_VER_PENDING,
    assign_project_coordinator_max,
    fetch_company_invite_by_token_max,
    get_company_name_max,
    is_max_visit_client_registered,
    mark_company_invite_used_max,
    record_user_pd_consent_max,
    resolve_tg_id_for_max_user,
    set_user_company_id_max,
    set_user_vacancy_alerts_opt_in_max,
    update_user_coordinator_profile_max,
    upsert_company_member_max,
)

logger = logging.getLogger(__name__)


def parse_ci_token(text: str | None) -> str | None:
    if not text:
        return None
    raw = (text or "").strip()
    low = raw.lower()
    if low.startswith("ci_") and len(low) > 3:
        return low[3:].strip()
    if low.startswith("invite_") and len(low) > 7:
        return low[7:].strip()
    m = re.search(r"(?:start=|/)?ci_([a-f0-9]{16,64})", raw, re.I)
    if m:
        return m.group(1).strip()
    return None


def invite_error_message(row: dict[str, Any] | None) -> str | None:
    if not row:
        return "Такого приглашения нет."
    if row.get("used_at"):
        return "Эта ссылка уже использована."
    if row.get("revoked_at"):
        return "Приглашение отозвано."
    exp = row.get("expires_at")
    if exp is not None:
        try:
            ref = exp.replace(tzinfo=None) if getattr(exp, "tzinfo", None) else exp
            if isinstance(ref, datetime) and datetime.now() > ref:
                return "Срок приглашения истёк."
        except Exception:
            pass
    return None


def invite_consent_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [link_btn("📄 Политика и согласие", PRIVACY_POLICY_URL)],
            [cb_btn("✅ Согласен с обработкой данных", "consent_ci_accept")],
            [cb_btn("⬅️ В меню", "main_menu")],
        ]
    )


def staff_mailing_keyboard() -> list[dict]:
    return inline_keyboard(
        [
            [
                cb_btn("✅ ДА", "ci_staff_alerts_yes"),
                cb_btn("❌ НЕТ", "ci_staff_alerts_no"),
            ],
        ]
    )


def _consent_scope_text(kind: str) -> str:
    role_ru = "координатора" if kind == "coordinator" else "исполнителя"
    return visit_flows._consent_gate_text(f"регистрация {role_ru}")


def start_invite_session(max_uid: int, token: str) -> dict[str, Any] | None:
    """Открыть сценарий по токену. None — не обработано."""
    tok = parse_ci_token(token) or (token or "").strip()
    if not tok:
        return None
    if is_max_visit_client_registered(int(max_uid)):
        return {
            "text": "Эта ссылка для исполнителя или координатора, не для заказчика.",
            "format": "markdown",
            "attachments": visit_card.main_menu_keyboard(max_uid),
        }
    row = fetch_company_invite_by_token_max(tok)
    err = invite_error_message(row)
    if err:
        return {
            "text": f"❌ {err}",
            "format": "markdown",
            "attachments": visit_card.main_menu_keyboard(max_uid),
        }
    kind = (row.get("invite_kind") or "staff").strip().lower()
    project_id = row.get("project_id")
    if project_id is not None:
        try:
            project_id = int(project_id)
        except (TypeError, ValueError):
            project_id = None
    created_by = row.get("created_by_tg_id")
    try:
        created_by = int(created_by) if created_by is not None else None
    except (TypeError, ValueError):
        created_by = None
    cname = get_company_name_max(int(row["company_id"]))
    role_ru = "координатора" if kind == "coordinator" else "исполнителя"
    visit_flows.SESSIONS[int(max_uid)] = {
        "flow": "company_invite",
        "step": "consent",
        "data": {
            "ci_invite_id": int(row["id"]),
            "ci_invite_token": str(row.get("token") or tok),
            "ci_company_id": int(row["company_id"]),
            "ci_invite_kind": kind,
            "ci_project_id": project_id,
            "ci_created_by_tg_id": created_by,
        },
    }
    return {
        "notification": " ",
        "text": (
            f"*Приглашение в команду «{cname}»* ({role_ru}).\n\n"
            + _consent_scope_text(kind)
        ),
        "format": "markdown",
        "attachments": invite_consent_keyboard(),
    }


def _begin_staff_join(max_uid: int, data: dict[str, Any], *, agency_path: bool) -> dict[str, Any]:
    company_id = int(data.get("ci_company_id") or 0)
    invite_id = int(data.get("ci_invite_id") or 0)
    if not company_id or not invite_id:
        visit_flows.clear_session(max_uid)
        return {
            "text": "Сессия сброшена. Откройте ссылку приглашения снова.",
            "format": "markdown",
            "attachments": visit_card.main_menu_keyboard(max_uid),
        }
    tg_id = resolve_tg_id_for_max_user(int(max_uid))
    set_user_company_id_max(tg_id, company_id)
    upsert_company_member_max(
        company_id=company_id,
        tg_id=tg_id,
        member_role="staff",
        verification_status=COMPANY_MEMBER_VER_PENDING,
        vacancy_alerts_opt_in=bool(data.get("ci_vacancy_alerts_yes")),
    )
    join_data: dict[str, Any] = {
        "join_consent_accepted": True,
        "join_entry": "profile",
        "company_invite_company_id": company_id,
        "company_invite_id": invite_id,
        "join_notify_client_tg_id": data.get("ci_created_by_tg_id"),
        "ci_vacancy_alerts_yes": bool(data.get("ci_vacancy_alerts_yes")),
        "join_profession_titles": [],
        "position": "",
        "canonical_user_tg_id": tg_id,
    }
    if agency_path:
        join_data.update(
            cooperation_mode=COOPERATION_MODE_PLATFORM,
            join_source="company_agency_pending",
            join_skip_tbank=False,
        )
        intro = (
            "Дальше — полная анкета исполнителя (как с визитки). "
            "После отправки заказчик проверит данные."
        )
    else:
        join_data.update(
            cooperation_mode=COOPERATION_MODE_CUSTOMER,
            join_source="customer_pool",
            join_skip_tbank=True,
        )
        intro = (
            "Дальше — анкета для команды заказчика (без личного кабинета Т-Банка). "
            "Ставки на сменах назначает заказчик или координатор."
        )
    visit_flows.SESSIONS[int(max_uid)] = {
        "flow": "join",
        "step": "profession_category",
        "data": join_data,
    }
    return {
        "notification": " ",
        "text": intro + "\n\n*ВЫБОР ПРОФЕССИИ*\n\nВыберите категорию 👇",
        "format": "markdown",
        "attachments": visit_card.profession_categories_keyboard(),
    }


def process_callback(
    max_uid: int,
    payload: str,
    session: dict[str, Any],
    sender: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if session.get("flow") != "company_invite":
        return None
    step = str(session.get("step") or "")
    data = session.setdefault("data", {})
    p = (payload or "").strip()

    if step == "consent" and p == "consent_ci_accept":
        kind = (data.get("ci_invite_kind") or "staff").strip().lower()
        tg_id = resolve_tg_id_for_max_user(int(max_uid))
        record_user_pd_consent_max(tg_id)
        if kind == "coordinator":
            session["step"] = "coord_full_name"
            cname = get_company_name_max(int(data.get("ci_company_id") or 0))
            return {
                "notification": "Согласие принято ✅",
                "text": (
                    f"*Регистрация координатора* для «{cname}».\n\n"
                    "Шаг 1 из 5. Введите *ФИО* полностью:"
                ),
                "format": "markdown",
                "attachments": inline_keyboard([[cb_btn("🔙 Отмена", "main_menu")]]),
            }
        session["step"] = "staff_alerts"
        return {
            "notification": "Согласие принято ✅",
            "text": (
                "Хотите получать *целевые рассылки* с предложениями от агентства "
                "и вакансии, которые публикуют *другие заказчики*?"
            ),
            "format": "markdown",
            "attachments": staff_mailing_keyboard(),
        }

    if p == "ci_staff_alerts_yes":
        data["ci_vacancy_alerts_yes"] = True
        set_user_vacancy_alerts_opt_in_max(resolve_tg_id_for_max_user(int(max_uid)), True)
        return _begin_staff_join(max_uid, data, agency_path=True)

    if p == "ci_staff_alerts_no":
        data["ci_vacancy_alerts_yes"] = False
        set_user_vacancy_alerts_opt_in_max(resolve_tg_id_for_max_user(int(max_uid)), False)
        return _begin_staff_join(max_uid, data, agency_path=False)

    return None


def process_text(
    max_uid: int,
    text: str,
    session: dict[str, Any],
    sender: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if session.get("flow") != "company_invite":
        return None
    step = str(session.get("step") or "")
    data = session.setdefault("data", {})
    raw = (text or "").strip()

    if step == "coord_full_name":
        if len(raw) < 3:
            return {"notification": " ", "text": "Укажите ФИО полностью (минимум 3 символа).", "format": "markdown"}
        data["coord_full_name"] = raw
        session["step"] = "coord_birth_date"
        return {"notification": " ", "text": "Шаг 2 из 5. Дата рождения (ДД.ММ.ГГГГ):", "format": "markdown"}

    if step == "coord_birth_date":
        m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", raw)
        if not m:
            return {"notification": " ", "text": "Формат: ДД.ММ.ГГГГ, например 15.03.1990", "format": "markdown"}
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            bd = datetime(y, mo, d).date()
        except ValueError:
            return {"notification": " ", "text": "Некорректная дата.", "format": "markdown"}
        if bd.year < 1940 or bd.year > datetime.now().year - 16:
            return {"notification": " ", "text": "Проверьте год рождения.", "format": "markdown"}
        data["coord_birth_date"] = bd.isoformat()
        session["step"] = "coord_position"
        return {"notification": " ", "text": "Шаг 3 из 5. Укажите *должность*:", "format": "markdown"}

    if step == "coord_position":
        if len(raw) < 2:
            return {"notification": " ", "text": "Укажите должность (минимум 2 символа).", "format": "markdown"}
        data["coord_position"] = raw
        session["step"] = "coord_phone"
        return {"notification": " ", "text": "Шаг 4 из 5. Номер телефона (+7… или 8…):", "format": "markdown"}

    if step == "coord_phone":
        digits = re.sub(r"\D", "", raw)
        if len(digits) < 10:
            return {"notification": " ", "text": "Укажите корректный номер телефона.", "format": "markdown"}
        data["coord_phone"] = raw
        session["step"] = "coord_email"
        return {"notification": " ", "text": "Шаг 5 из 5. Email:", "format": "markdown"}

    if step == "coord_email":
        if "@" not in raw or len(raw) < 5:
            return {"notification": " ", "text": "Укажите корректный email.", "format": "markdown"}
        invite_id = data.get("ci_invite_id")
        company_id = data.get("ci_company_id")
        project_id = data.get("ci_project_id")
        if not invite_id or not company_id:
            visit_flows.clear_session(max_uid)
            return {
                "text": "Сессия сброшена. Откройте ссылку приглашения снова.",
                "format": "markdown",
                "attachments": visit_card.main_menu_keyboard(max_uid),
            }
        row = fetch_company_invite_by_token_max(str(data.get("ci_invite_token") or ""))
        err = invite_error_message(row)
        if err:
            visit_flows.clear_session(max_uid)
            return {
                "text": f"❌ {err}",
                "format": "markdown",
                "attachments": visit_card.main_menu_keyboard(max_uid),
            }
        tg_id = resolve_tg_id_for_max_user(int(max_uid))
        try:
            set_user_company_id_max(tg_id, int(company_id))
            update_user_coordinator_profile_max(
                tg_id,
                full_name=str(data.get("coord_full_name") or ""),
                birth_date_iso=str(data.get("coord_birth_date") or ""),
                position=str(data.get("coord_position") or ""),
                phone=str(data.get("coord_phone") or ""),
                email=raw,
            )
            upsert_company_member_max(
                company_id=int(company_id),
                tg_id=tg_id,
                member_role="coordinator",
            )
            if project_id:
                assign_project_coordinator_max(int(project_id), tg_id)
            mark_company_invite_used_max(int(invite_id), tg_id)
        except Exception:
            logger.exception("coord_reg_finish max_uid=%s", max_uid)
            return {
                "notification": "Ошибка",
                "text": "Не удалось сохранить данные. Попробуйте позже.",
                "format": "markdown",
            }
        visit_flows.clear_session(max_uid)
        cname = get_company_name_max(int(company_id))
        extra = f"\nНазначен на проект №{project_id}." if project_id else ""
        return {
            "notification": "Готово ✅",
            "text": (
                f"✅ Регистрация завершена.\n"
                f"Вы координатор в «{cname}».{extra}\n\n"
                "Нажмите /start — откроется меню."
            ),
            "format": "markdown",
            "attachments": visit_card.main_menu_keyboard(max_uid),
        }

    return None


def _tg_invite_link(token: str) -> str:
    from config import CONTACT_TELEGRAM

    un = (CONTACT_TELEGRAM or "").strip().lstrip("@")
    if not un:
        return f"start=ci_{token}"
    return f"https://t.me/{un}?start=ci_{token}"


def invite_share_text_max(token: str) -> str:
    """Текст для заказчика: как передать ссылку исполнителю."""
    max_cmd = f"/start ci_{token}"
    return (
        "*Приглашение в команду*\n\n"
        "Исполнитель может принять приглашение *в боте MAX* — отправьте в чат:\n"
        f"`{max_cmd}`\n\n"
        f"Или ссылка Telegram: {_tg_invite_link(token)}"
    )
