"""Дозаполнение анкеты исполнителя по запросу менеджера (MAX)."""
from __future__ import annotations

import re
from typing import Any

import visit_card
import visit_join_validators
from join_clarification_db import (
    CLARIFICATION_FLAG_LABELS_RU,
    VALID_CLARIFICATION_FLAG_CODES,
    acknowledge_join_clarification_note_only,
    apply_join_clarification_patch,
    get_max_join_clarification_context,
    get_max_worker_status,
)
from funnel_db import WORKER_STATUS_CLARIFICATION

_FLAG_PHOTO = frozenset({"pm", "pr", "sf"})


def _prompt_ru(code: str) -> str:
    return {
        "pm": "Пришлите *фото главного разворота паспорта* (как в анкете).",
        "pr": "Пришлите *фото страницы с пропиской*.",
        "ps": "Введите *серию и номер паспорта* одним сообщением.",
        "tx": "Введите *ИНН* (10 или 12 цифр).",
        "sf": "Пришлите *селфи* (фото).",
        "fn": "Введите *ФИО* полностью.",
        "ph": "Введите *номер телефона*.",
        "mb": "Введите *номер медкнижки* (и при необходимости срок в том же сообщении).",
    }.get(code, "Пришлите запрошенные данные одним сообщением.")


def _patch_from_text(code: str, text: str, *, file_ref: str = "") -> dict[str, Any]:
    if code in _FLAG_PHOTO:
        if not file_ref:
            raise ValueError("photo")
        if code == "pm":
            return {"passport_main_ref": file_ref, "passport_main_file_id": file_ref}
        if code == "pr":
            return {"passport_reg_ref": file_ref, "passport_reg_file_id": file_ref}
        return {"selfie_ref": file_ref, "selfie_url": file_ref}
    raw_t = (text or "").strip()
    if not raw_t:
        raise ValueError("empty")
    if code == "tx":
        inn = re.sub(r"\D", "", raw_t)
        if len(inn) not in (10, 12):
            raise ValueError("inn")
        return {"tax_inn": inn}
    if code == "ps":
        return {"passport_sn": raw_t[:80]}
    if code == "fn":
        if not visit_join_validators.validate_join_full_name(raw_t):
            raise ValueError("name")
        return {"full_name": raw_t.strip()}
    if code == "ph":
        ph = re.sub(r"\D", "", raw_t)
        if len(ph) < 10:
            raise ValueError("phone")
        return {"phone": ph}
    if code == "mb":
        return {"medbook_number": raw_t[:120]}
    raise ValueError("unknown")


def start_clarification_input(max_uid: int, s: dict[str, Any]) -> dict[str, Any] | None:
    if get_max_worker_status(max_uid) != WORKER_STATUS_CLARIFICATION:
        return {
            "notification": "Сейчас не требуется дозаполнение.",
            "text": "Статус анкеты изменился. Откройте главное меню (/start).",
            "format": "markdown",
            "attachments": visit_card.main_menu_keyboard(),
        }
    ctx = get_max_join_clarification_context(max_uid)
    flags = ctx.get("flags") or []
    if not flags:
        return {
            "notification": "Нет полей для дозаполнения",
            "text": (
                "Список полей пуст. Если менеджер оставил только комментарий — "
                "нажмите «Отправить на проверку снова» в меню."
            ),
            "format": "markdown",
            "attachments": visit_card.worker_clarification_keyboard(),
        }
    code = str(flags[0]).strip().lower()
    if code not in VALID_CLARIFICATION_FLAG_CODES:
        return {
            "notification": "Ошибка запроса",
            "text": "Некорректный запрос. Свяжитесь с менеджером.",
            "format": "markdown",
            "attachments": visit_card.worker_clarification_keyboard(),
        }
    s["flow"] = "clarification"
    s["step"] = "waiting_input"
    s.setdefault("data", {})["clar_code"] = code
    label = CLARIFICATION_FLAG_LABELS_RU.get(code, code)
    return {
        "notification": "Дозаполнение",
        "text": f"✏️ *Дозаполнение:* {label}\n\n{_prompt_ru(code)}",
        "format": "markdown",
        "attachments": visit_card.back_to_main_keyboard(),
    }


def process_clarification_ack(max_uid: int) -> dict[str, Any]:
    res = acknowledge_join_clarification_note_only(max_uid)
    if not res:
        return {
            "notification": "Не удалось обновить",
            "text": "Не удалось обновить статус. Попробуйте позже или напишите менеджеру.",
            "format": "markdown",
            "attachments": visit_card.worker_clarification_keyboard(),
        }
    if res.get("error") == "flags_remain":
        return {
            "notification": "Сначала дозаполните блоки",
            "text": "Сначала дозаполните запрошенные блоки кнопкой «Дозаполнить».",
            "format": "markdown",
            "attachments": visit_card.worker_clarification_keyboard(),
        }
    from visit_flows import clear_session

    clear_session(max_uid)
    return {
        "notification": "Отправлено на проверку",
        "text": (
            "✅ Заявка снова передана на проверку. Ожидайте решения администратора.\n\n"
            "_Главное меню — /start._"
        ),
        "format": "markdown",
        "attachments": visit_card.worker_pending_verification_keyboard(),
    }


def process_clarification_text(
    max_uid: int,
    s: dict[str, Any],
    text: str,
    *,
    file_ref: str = "",
) -> dict[str, Any] | None:
    if s.get("flow") != "clarification" or s.get("step") != "waiting_input":
        return None
    data = s.setdefault("data", {})
    code = str(data.get("clar_code") or "").strip().lower()
    if code not in VALID_CLARIFICATION_FLAG_CODES:
        return {
            "text": "Сессия сброшена. Откройте /start.",
            "format": "markdown",
            "attachments": visit_card.main_menu_keyboard(),
        }
    try:
        patch = _patch_from_text(code, text, file_ref=file_ref)
    except ValueError as e:
        arg = str(e.args[0]) if e.args else ""
        err = {
            "photo": "Нужно отправить фото.",
            "empty": "Сообщение пустое — пришлите данные ещё раз.",
            "inn": "ИНН должен содержать 10 или 12 цифр.",
            "phone": "Укажите корректный номер телефона (минимум 10 цифр).",
            "name": "Проверьте ФИО (минимум 2 слова).",
        }.get(arg, "Проверьте формат и отправьте снова.")
        return {
            "text": err,
            "format": "markdown",
            "attachments": visit_card.back_to_main_keyboard(),
        }

    res = apply_join_clarification_patch(max_uid, patch)
    if not res:
        return {
            "text": "Не удалось сохранить. Попробуйте позже или напишите менеджеру.",
            "format": "markdown",
            "attachments": visit_card.worker_clarification_keyboard(),
        }
    if res.get("error") == "not_in_clarification":
        from visit_flows import clear_session

        clear_session(max_uid)
        return {
            "text": "Статус изменился. Откройте главное меню (/start).",
            "format": "markdown",
            "attachments": visit_card.main_menu_keyboard(),
        }
    if res.get("returned_to_review"):
        from visit_flows import clear_session

        clear_session(max_uid)
        return {
            "notification": "Спасибо!",
            "text": (
                "✅ Все запрошенные блоки заполнены; анкета снова на проверке у администратора."
            ),
            "format": "markdown",
            "attachments": visit_card.worker_pending_verification_keyboard(),
        }
    remaining = res.get("remaining_flags") or []
    if not remaining:
        from visit_flows import clear_session

        clear_session(max_uid)
        return {
            "text": "✅ Спасибо! Анкета снова на проверке у администратора.",
            "format": "markdown",
            "attachments": visit_card.worker_pending_verification_keyboard(),
        }
    nxt = str(remaining[0]).strip().lower()
    data["clar_code"] = nxt
    label = CLARIFICATION_FLAG_LABELS_RU.get(nxt, nxt)
    return {
        "notification": "Дальше",
        "text": f"✏️ *Дальше:* {label}\n\n{_prompt_ru(nxt)}",
        "format": "markdown",
        "attachments": visit_card.back_to_main_keyboard(),
    }
