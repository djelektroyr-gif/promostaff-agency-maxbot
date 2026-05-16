"""Один пользователь на телефон: резолв при регистрации в MAX (общая БД с Telegram)."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Literal

from funnel_db import (
    WORKER_STATUS_APPROVED,
    WORKER_STATUS_CLARIFICATION,
    WORKER_STATUS_REJECTED,
    connection,
    worker_tg_id_for_max,
)

logger = logging.getLogger(__name__)

MAX_TG_SYNTHETIC_LEAST = 10**15

ROLE_SWITCH_VIA_ADMIN_FOOTER_RU = (
    "\n\nВторая роль возможна только после удаления текущего профиля администратором в базе."
)

IntendedRole = Literal["client", "worker"]


@dataclass(frozen=True)
class PhoneResolveResult:
    action: str
    canonical_tg_id: int | None = None
    notification: str = ""
    text: str = ""
    format: str = "markdown"


def is_synthetic_tg_id(tg_id: int | None) -> bool:
    return tg_id is not None and int(tg_id) >= MAX_TG_SYNTHETIC_LEAST


def normalize_phone_ru(raw: str | None) -> str:
    raw_s = str(raw or "").strip()
    s = re.sub(r"\D+", "", raw_s)
    if not s:
        return ""
    if len(s) == 11 and s.startswith("8"):
        s = "7" + s[1:]
    elif len(s) == 10 and s.startswith("9"):
        s = "7" + s
    if len(s) == 11 and s.startswith("7"):
        return s
    return ""


def _phone_digits_match(stored: str | None, target_norm: str) -> bool:
    row_norm = normalize_phone_ru(stored)
    if not row_norm or not target_norm:
        return False
    return row_norm == target_norm


def find_users_by_phone(phone: str) -> list[dict[str, Any]]:
    """Все строки users с совпадающим нормализованным телефоном."""
    target = normalize_phone_ru(phone)
    if not target:
        return []
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT tg_id, max_user_id, role, full_name, phone, created_at
                    FROM users
                    WHERE phone IS NOT NULL AND btrim(phone) <> ''
                    """
                )
                rows = cur.fetchall() or []
        out: list[dict[str, Any]] = []
        for r in rows:
            d = {
                "tg_id": int(r[0]),
                "max_user_id": int(r[1]) if r[1] is not None else None,
                "role": (r[2] or "").strip().lower(),
                "full_name": r[3] or "",
                "phone": r[4] or "",
            }
            if _phone_digits_match(d.get("phone"), target):
                out.append(d)
        return out
    except Exception:
        logger.exception("find_users_by_phone")
        return []


def _user_is_client(tg_id: int) -> bool:
    tid = int(tg_id)
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM clients WHERE user_id = %s LIMIT 1", (tid,))
                if cur.fetchone():
                    return True
                cur.execute("SELECT 1 FROM visit_clients WHERE user_id = %s LIMIT 1", (tid,))
                if cur.fetchone():
                    return True
                cur.execute(
                    "SELECT 1 FROM users WHERE tg_id = %s AND lower(COALESCE(role, '')) = 'client' LIMIT 1",
                    (tid,),
                )
                return bool(cur.fetchone())
    except Exception:
        logger.exception("_user_is_client tg_id=%s", tid)
    return False


def _user_worker_status(tg_id: int) -> str | None:
    tid = int(tg_id)
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COALESCE(status, 'new') FROM workers WHERE user_id = %s LIMIT 1",
                    (tid,),
                )
                row = cur.fetchone()
                return str(row[0]).strip().lower() if row else None
    except Exception:
        logger.exception("_user_worker_status tg_id=%s", tid)
    return None


def _user_is_active_worker(tg_id: int) -> bool:
    st = _user_worker_status(tg_id)
    return bool(st and st != WORKER_STATUS_REJECTED)


def _client_verified_at_tg(tg_id: int) -> bool:
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM visit_clients
                    WHERE user_id = %s AND verified_at IS NOT NULL
                    LIMIT 1
                    """,
                    (int(tg_id),),
                )
                return bool(cur.fetchone())
    except Exception:
        logger.exception("_client_verified_at_tg tg_id=%s", tg_id)
    return False


def link_max_user_id(canonical_tg_id: int, max_user_id: int) -> None:
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE users SET max_user_id = %s, updated_at = NOW()
                    WHERE tg_id = %s
                      AND (max_user_id IS NULL OR max_user_id = %s)
                    """,
                    (int(max_user_id), int(canonical_tg_id), int(max_user_id)),
                )
    except Exception:
        logger.exception("link_max_user_id tg=%s max=%s", canonical_tg_id, max_user_id)


def resolve_registration_by_phone(
    max_user_id: int,
    phone: str,
    intended_role: IntendedRole,
) -> PhoneResolveResult:
    """
    После ввода телефона в регистрации MAX.
    action: continue | resume_* | role_conflict | ambiguous | max_conflict
    """
    uid = int(max_user_id)
    norm_phone = normalize_phone_ru(phone)
    synthetic = worker_tg_id_for_max(uid)
    rows = find_users_by_phone(phone) if norm_phone else []

    if len(rows) > 1:
        return PhoneResolveResult(
            action="ambiguous",
            notification="Нужна помощь менеджера",
            text=(
                "По этому номеру в базе несколько записей. "
                "Напишите в агентство — мы объединим профиль вручную."
            ),
        )

    if rows:
        row = rows[0]
        ctg = int(row["tg_id"])
        ex_max = row.get("max_user_id")
        if ex_max is not None and int(ex_max) != uid:
            return PhoneResolveResult(
                action="max_conflict",
                notification="Номер занят",
                text=(
                    "Этот телефон уже привязан к другому аккаунту MAX. "
                    "Если это вы — напишите менеджеру агентства."
                ),
            )

        is_cl = _user_is_client(ctg)
        is_wr = _user_is_active_worker(ctg)

        if intended_role == "worker":
            if is_cl:
                return PhoneResolveResult(
                    action="role_conflict",
                    notification="Другая роль",
                    text=(
                        "По этому номеру вы уже зарегистрированы как *заказчик*. "
                        "Анкета исполнителя для этого профиля недоступна."
                        + ROLE_SWITCH_VIA_ADMIN_FOOTER_RU
                    ),
                )
            if is_wr:
                link_max_user_id(ctg, uid)
                st = _user_worker_status(ctg)
                if st == WORKER_STATUS_APPROVED:
                    return PhoneResolveResult(
                        action="resume_worker_verified",
                        canonical_tg_id=ctg,
                        notification="Уже в команде",
                        text="У вас уже есть профиль исполнителя. Главное меню — ниже.",
                    )
                if st == WORKER_STATUS_CLARIFICATION:
                    return PhoneResolveResult(
                        action="resume_worker_clarification",
                        canonical_tg_id=ctg,
                        notification="Нужны уточнения",
                        text="По анкете запрошены уточнения — откройте главное меню (/start).",
                    )
                if st and st != WORKER_STATUS_REJECTED:
                    return PhoneResolveResult(
                        action="resume_worker_pending",
                        canonical_tg_id=ctg,
                        notification="На проверке",
                        text=(
                            "*Анкета уже отправлена.*\n\n"
                            "Дождитесь подтверждения администратором."
                        ),
                    )
            link_max_user_id(ctg, uid)
            return PhoneResolveResult(action="continue", canonical_tg_id=ctg)

        if is_wr:
            return PhoneResolveResult(
                action="role_conflict",
                notification="Другая роль",
                text=(
                    "По этому номеру вы уже зарегистрированы как *исполнитель*. "
                    "Регистрация заказчика недоступна."
                    + ROLE_SWITCH_VIA_ADMIN_FOOTER_RU
                ),
            )
        if is_cl:
            link_max_user_id(ctg, uid)
            if _client_verified_at_tg(ctg):
                return PhoneResolveResult(
                    action="resume_client_verified",
                    canonical_tg_id=ctg,
                    notification="Уже зарегистрированы",
                    text="Вы уже зарегистрированы как заказчик. Меню — ниже.",
                )
            return PhoneResolveResult(
                action="resume_client_pending",
                canonical_tg_id=ctg,
                notification="На проверке",
                text=(
                    "Регистрация заказчика уже принята и на проверке у администратора.\n\n"
                    "Пока можете написать менеджеру."
                ),
            )
        link_max_user_id(ctg, uid)
        return PhoneResolveResult(action="continue", canonical_tg_id=ctg)

    return PhoneResolveResult(action="continue", canonical_tg_id=synthetic)
