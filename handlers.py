"""
Обработка MAX: визитка как в Telegram, плюс нативные возможности MAX
(в т.ч. короткий текст в `notification` при ответе на callback — «всплывашка» у кнопки).
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import defaultdict
from typing import Any

from config import MAX_TOKEN
from funnel_store import funnel_sync_session
from max_client import post_answer, post_message

import visit_card
import visit_flows

logger = logging.getLogger(__name__)
_UI_DUPLICATE_MIN_INTERVAL_SEC = 6.0
_UI_SPAM_ERRORS_TOTAL = 0
_UI_SPAM_ERRORS_BY_USER: dict[int, int] = defaultdict(int)


def _text_reply_dedupe_key(max_uid: int, reply: dict[str, Any]) -> str | None:
    """Ключ анти-спама для text-ответов: одинаковый шаг + одинаковый текст не шлём повторно."""
    txt = str(reply.get("text") or "").strip()
    if not txt:
        return None
    s = visit_flows.SESSIONS.get(max_uid) or {}
    flow = str(s.get("flow") or "")
    step = str(s.get("step") or "")
    return f"{flow}|{step}|{txt}"


def _is_error_like_reply_text(text: str) -> bool:
    s = (text or "").strip().lower()
    if not s:
        return False
    return any(
        x in s
        for x in (
            "ошиб",
            "сначала",
            "проверьте",
            "нужно",
            "некоррект",
            "не найден",
            "недоступно",
        )
    )


def _is_duplicate_text_reply(max_uid: int, reply: dict[str, Any]) -> bool:
    global _UI_SPAM_ERRORS_TOTAL
    key = _text_reply_dedupe_key(max_uid, reply)
    if not key:
        return False
    s = visit_flows.SESSIONS.get(max_uid)
    if not isinstance(s, dict):
        return False
    last = str(s.get("_ui_last_text_reply_key") or "")
    now = time.time()
    try:
        last_ts = float(s.get("_ui_last_text_reply_at") or 0.0)
    except (TypeError, ValueError):
        last_ts = 0.0
    if last == key:
        if now - last_ts < _UI_DUPLICATE_MIN_INTERVAL_SEC:
            if _is_error_like_reply_text(str(reply.get("text") or "")):
                _UI_SPAM_ERRORS_TOTAL += 1
                _UI_SPAM_ERRORS_BY_USER[int(max_uid)] += 1
            return True
    s["_ui_last_text_reply_key"] = key
    s["_ui_last_text_reply_at"] = now
    return False


def get_ui_spam_metrics() -> dict[str, int]:
    return {
        "ui_spam_errors_total": int(_UI_SPAM_ERRORS_TOTAL),
        "ui_spam_users_count": int(len(_UI_SPAM_ERRORS_BY_USER)),
    }


def _short_notification_from_text(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return " "
    # Убираем markdown-шум для короткой всплывашки MAX.
    one_line = re.sub(r"[*_`#>\[\]\(\)]", "", raw).splitlines()[0].strip()
    if len(one_line) > 90:
        one_line = one_line[:87].rstrip() + "..."
    return one_line or " "


def _is_escape_only_keyboard(attachments: Any) -> bool:
    """Клавиатура только с кнопками выхода из сценария (главное меню/назад)."""
    if not isinstance(attachments, list) or not attachments:
        return False
    root = attachments[0] if isinstance(attachments[0], dict) else {}
    payload = root.get("payload") if isinstance(root, dict) else {}
    buttons = payload.get("buttons") if isinstance(payload, dict) else None
    if not isinstance(buttons, list) or not buttons:
        return False
    seen_payloads: set[str] = set()
    for row in buttons:
        if not isinstance(row, list):
            continue
        for btn in row:
            if not isinstance(btn, dict):
                continue
            p = str(btn.get("payload") or "").strip()
            if p:
                seen_payloads.add(p)
    if not seen_payloads:
        return False
    return seen_payloads.issubset({"main_menu", "back", "back_to_main"})


def _remove_registration_exit_buttons(attachments: Any) -> Any:
    """Убирает из inline-клавиатур только выход из сценария регистрации."""
    if not isinstance(attachments, list) or not attachments:
        return attachments
    out: list[Any] = []
    blocked_payloads = {
        "main_menu",
        "back_to_main",
        "visit_public_menu",
        "consent_client_visit_accept",
        "consent_join_accept",
        "consent_order_accept",
        "consent_question_accept",
    }
    for item in attachments:
        if not isinstance(item, dict):
            out.append(item)
            continue
        if item.get("type") != "inline_keyboard":
            out.append(item)
            continue
        payload = item.get("payload")
        buttons = payload.get("buttons") if isinstance(payload, dict) else None
        if not isinstance(buttons, list):
            out.append(item)
            continue
        has_consent_gate = False
        for row in buttons:
            if not isinstance(row, list):
                continue
            for btn in row:
                if not isinstance(btn, dict):
                    continue
                p0 = str(btn.get("payload") or "").strip()
                if p0 in {
                    "consent_client_visit_accept",
                    "consent_join_accept",
                    "consent_order_accept",
                    "consent_question_accept",
                }:
                    has_consent_gate = True
                    break
            if has_consent_gate:
                break
        if has_consent_gate:
            continue
        new_buttons: list[list[dict[str, Any]]] = []
        for row in buttons:
            if not isinstance(row, list):
                continue
            new_row: list[dict[str, Any]] = []
            for btn in row:
                if not isinstance(btn, dict):
                    continue
                p = str(btn.get("payload") or "").strip()
                if p in blocked_payloads:
                    continue
                new_row.append(btn)
            if new_row:
                new_buttons.append(new_row)
        if new_buttons:
            cloned = dict(item)
            cloned_payload = dict(payload or {})
            cloned_payload["buttons"] = new_buttons
            cloned["payload"] = cloned_payload
            out.append(cloned)
    return out


def _strip_registration_escape_keyboard(max_uid: int, reply: dict[str, Any]) -> dict[str, Any]:
    """В регистрации не показываем кнопки выхода после согласия (паритет с Telegram)."""
    s = visit_flows.SESSIONS.get(int(max_uid)) or {}
    flow = str(s.get("flow") or "")
    step = str(s.get("step") or "")
    if flow not in {"join", "client_visit"}:
        return reply
    if step in {"consent"}:
        return reply
    out = dict(reply)
    out["attachments"] = _remove_registration_exit_buttons(out.get("attachments"))
    if flow == "join":
        # Чистый экран в мастере исполнителя: на текстовых шагах не держим inline-кнопки.
        join_text_only_steps = {
            "full_name",
            "phone",
            "birth_date",
            "tax_se_inn",
            "tax_fl_inn",
            "tax_ip_inn",
            "snils",
            "contact_email",
            "gph_bank_name",
            "gph_bik",
            "gph_settlement_account",
            "gph_corr_account",
            "experience_desc",
            "param_height",
            "param_weight",
            "param_shoe",
            "medbook_number",
            "skills",
            "city",
            "work_metro",
            "passport_sn",
            "passport_issued_by",
            "passport_issued_on",
            "registration_address",
            "portfolio_url",
            "portfolio_pdf",
            "selfie",
            "passport_main",
            "passport_reg",
        }
        if step in join_text_only_steps:
            out["attachments"] = []
    if _is_escape_only_keyboard(out.get("attachments")):
        # В MAX при отсутствии attachments у callback-ответа старая клавиатура может остаться.
        # Передаём пустой список, чтобы явно очистить кнопки предыдущего шага.
        out["attachments"] = []
    return out


async def _sync_funnel(max_uid: int) -> None:
    await asyncio.to_thread(
        funnel_sync_session,
        max_uid,
        visit_flows.SESSIONS.get(max_uid),
    )


def _max_uid_from_update(update_type: str, body: dict[str, Any]) -> int | None:
    if update_type == "user_added":
        u = body.get("user") or {}
        uid = u.get("user_id")
        return int(uid) if uid is not None else None
    if update_type == "bot_started":
        u = body.get("user") or {}
        uid = u.get("user_id")
        return int(uid) if uid is not None else None
    if update_type == "message_created":
        msg = body.get("message") or {}
        sender = msg.get("sender") or {}
        if sender.get("is_bot"):
            return None
        uid = sender.get("user_id")
        return int(uid) if uid is not None else None
    if update_type == "message_callback":
        cb = body.get("callback") or {}
        u = cb.get("user") or {}
        uid = u.get("user_id")
        return int(uid) if uid is not None else None
    return None


def _sender_from_message(body: dict[str, Any]) -> dict[str, Any] | None:
    msg = body.get("message") or {}
    s = msg.get("sender")
    return s if isinstance(s, dict) else None


async def _send_message(max_uid: int, body: dict[str, Any]) -> None:
    body = _strip_registration_escape_keyboard(max_uid, dict(body))
    body.pop("notification", None)
    await post_message(MAX_TOKEN, max_uid, body)


async def _answer_message(callback_id: str, max_uid: int, msg: dict[str, Any]) -> None:
    msg = _strip_registration_escape_keyboard(max_uid, dict(msg))
    raw = msg.pop("notification", None)
    notif = (raw if isinstance(raw, str) else None) or " "
    if notif.strip() == "":
        notif = " "
    if notif == " " and _is_error_like_reply_text(str(msg.get("text") or "")):
        notif = _short_notification_from_text(str(msg.get("text") or ""))
    notif = notif.strip() or " "
    api_msg = {k: v for k, v in msg.items()}
    ok = await post_answer(
        MAX_TOKEN,
        callback_id,
        {"notification": notif[:200], "message": api_msg},
    )
    if not ok:
        logger.warning("post_answer failed, sending new message")
        await _send_message(max_uid, msg)


async def process_update(body: dict[str, Any]) -> None:
    update_type = body.get("update_type") or ""
    max_uid = _max_uid_from_update(update_type, body)
    logger.debug("MAX update: type=%r max_uid=%r", update_type, max_uid)

    if update_type in ("bot_started", "user_added") and max_uid is not None:
        visit_flows.clear_session(max_uid)
        await _send_message(max_uid, visit_card.message_role_home(max_uid))
        await _sync_funnel(max_uid)
        return

    if update_type == "message_created" and max_uid is not None:
        msg = body.get("message") or {}
        inner = msg.get("body") or {}
        text = (inner.get("text") or "").strip()
        sender = _sender_from_message(body)

        if re.match(r"^/(start|старт)\b", text, re.I):
            visit_flows.clear_session(max_uid)
            await _send_message(max_uid, visit_card.message_role_home(max_uid))
            await _sync_funnel(max_uid)
            return
        if re.match(r"^/admin\b", text, re.I):
            visit_flows.clear_session(max_uid)
            if visit_card.is_admin_user(max_uid):
                msg = await visit_flows.process_callback(max_uid, "admin_agency_hub", sender)
                if msg is not None:
                    await _send_message(max_uid, msg)
                else:
                    await _send_message(max_uid, visit_card.message_role_home(max_uid))
            else:
                await _send_message(
                    max_uid,
                    {
                        "text": "Раздел /admin доступен только администраторам агентства.",
                        "format": "markdown",
                        "attachments": visit_card.main_menu_keyboard(max_uid),
                    },
                )
            await _sync_funnel(max_uid)
            return
        if re.match(r"^/fsm\b", text, re.I):
            if not visit_card.is_admin_user(max_uid):
                await _send_message(
                    max_uid,
                    {
                        "text": "Команда /fsm доступна только администраторам.",
                        "format": "markdown",
                        "attachments": visit_card.main_menu_keyboard(max_uid),
                    },
                )
                await _sync_funnel(max_uid)
                return
            m = re.match(r"^/fsm(?:\s+(\d+))?\s*$", text, re.I)
            if not m:
                await _send_message(
                    max_uid,
                    {
                        "text": "Использование: `/fsm` или `/fsm <user_id>`",
                        "format": "markdown",
                        "attachments": visit_card.main_menu_keyboard(max_uid),
                    },
                )
                await _sync_funnel(max_uid)
                return
            target_uid = int(m.group(1)) if m.group(1) else int(max_uid)
            await _send_message(
                max_uid,
                {
                    "text": visit_flows.debug_session_text(target_uid),
                    "format": "markdown",
                    "attachments": visit_card.main_menu_keyboard(max_uid),
                },
            )
            await _sync_funnel(max_uid)
            return
        if re.match(r"^(меню|menu)\b", text, re.I):
            visit_flows.clear_session(max_uid)
            await _send_message(max_uid, visit_card.message_role_home(max_uid))
            await _sync_funnel(max_uid)
            return

        reply = await visit_flows.process_text(max_uid, text, sender, inner)
        await _sync_funnel(max_uid)
        if reply is not None:
            if _is_duplicate_text_reply(max_uid, reply):
                logger.debug("skip duplicate text reply uid=%s", max_uid)
                return
            await _send_message(max_uid, reply)
        return

    if update_type == "message_callback" and max_uid is not None:
        cb = body.get("callback") or {}
        callback_id = (cb.get("callback_id") or "").strip()
        raw_pl = cb.get("payload")
        if isinstance(raw_pl, dict):
            payload = str(
                raw_pl.get("payload")
                or raw_pl.get("callback_payload")
                or raw_pl.get("data")
                or ""
            ).strip()
        else:
            payload = (raw_pl or "").strip() if raw_pl is not None else ""
        if not callback_id:
            return

        if payload == "none":
            await post_answer(MAX_TOKEN, callback_id, {"notification": " "})
            return

        if payload == "visit_public_menu":
            visit_flows.clear_session(max_uid)
            await _answer_message(callback_id, max_uid, visit_card.message_main_menu(max_uid))
            await _sync_funnel(max_uid)
            return

        sender_cb = cb.get("user") if isinstance(cb.get("user"), dict) else None
        flow_reply = await visit_flows.process_callback(max_uid, payload, sender_cb)
        if flow_reply is not None:
            await _answer_message(callback_id, max_uid, flow_reply)
            await _sync_funnel(max_uid)
            return

        if payload in ("main_menu", "back", "back_to_main"):
            visit_flows.clear_session(max_uid)
            await _answer_message(callback_id, max_uid, visit_card.message_role_home(max_uid))
            await _sync_funnel(max_uid)
            return

        if payload == "calculate":
            msg = visit_flows.route_calculate_button(max_uid)
            await _answer_message(callback_id, max_uid, msg)
            await _sync_funnel(max_uid)
            return

        if payload == "client_visit_menu":
            msg = visit_flows.start_client_visit_menu(max_uid)
            await _answer_message(callback_id, max_uid, msg)
            await _sync_funnel(max_uid)
            return

        if payload == "client_quote_quick":
            msg = visit_flows.start_client_quote(max_uid, preset="quick")
            await _answer_message(callback_id, max_uid, msg)
            await _sync_funnel(max_uid)
            return

        if payload == "client_quote_cp":
            msg = visit_flows.start_client_quote(max_uid, preset="cp")
            await _answer_message(callback_id, max_uid, msg)
            await _sync_funnel(max_uid)
            return

        if payload == "client_quote_listing":
            msg = visit_flows.start_listing_order(max_uid)
            await _answer_message(callback_id, max_uid, msg)
            await _sync_funnel(max_uid)
            return

        if payload == "ask_manager":
            msg = visit_flows.start_question(max_uid)
            await _answer_message(callback_id, max_uid, msg)
            await _sync_funnel(max_uid)
            return

        if payload in ("contact_show_phone", "contact_show_email"):
            from config import CONTACT_EMAIL, CONTACT_PHONE

            note = CONTACT_PHONE if payload == "contact_show_phone" else CONTACT_EMAIL
            await post_answer(
                MAX_TOKEN,
                callback_id,
                {"notification": (note or "")[:200]},
            )
            return

        if payload == "join_team":
            await _answer_message(callback_id, max_uid, visit_flows.show_join_team(max_uid))
            await _sync_funnel(max_uid)
            return

        if payload == "requirements":
            await _answer_message(callback_id, max_uid, visit_flows.show_requirements(max_uid))
            await _sync_funnel(max_uid)
            return

        if payload == "vacancies":
            await _answer_message(callback_id, max_uid, visit_flows.show_vacancies_list(max_uid))
            await _sync_funnel(max_uid)
            return

        if payload.startswith("vac_view_"):
            msg = visit_flows.show_vacancy_detail(max_uid, payload)
            if msg is not None:
                await _answer_message(callback_id, max_uid, msg)
            else:
                await post_answer(MAX_TOKEN, callback_id, {"notification": "Неизвестная вакансия"})
            await _sync_funnel(max_uid)
            return

        if payload.startswith("vac_apply_"):
            msg = visit_flows.join_from_vacancy(max_uid, payload)
            if msg is not None:
                await _answer_message(callback_id, max_uid, msg)
            else:
                await post_answer(MAX_TOKEN, callback_id, {"notification": " "})
            await _sync_funnel(max_uid)
            return

        if payload == "fill_anketa":
            msg = visit_flows.start_fill_anketa(max_uid)
            await _answer_message(callback_id, max_uid, msg)
            await _sync_funnel(max_uid)
            return

        static_msg = visit_card.message_for_static_payload(payload)
        if static_msg is not None:
            visit_flows.clear_session(max_uid)
            await _answer_message(callback_id, max_uid, static_msg)
        elif visit_card.is_visit_flow_payload(payload):
            if payload.startswith(("prof_cat:", "prof_pick:", "prof_custom:")) or payload == "prof_back":
                await _answer_message(
                    callback_id,
                    max_uid,
                    {
                        "notification": "Сессия сброшена",
                        "text": (
                            "*Сессия анкеты устарела или была сброшена.*\n\n"
                            "Откройте *«Хочу в команду»* в меню и пройдите шаги снова "
                            "(один инстанс бота без перезапуска между шагами)."
                        ),
                        "format": "markdown",
                        "attachments": visit_card.main_menu_keyboard(),
                    },
                )
            else:
                await post_answer(MAX_TOKEN, callback_id, {"notification": " "})
        else:
            visit_flows.clear_session(max_uid)
            await post_answer(MAX_TOKEN, callback_id, {"notification": " "})
        await _sync_funnel(max_uid)
        return
