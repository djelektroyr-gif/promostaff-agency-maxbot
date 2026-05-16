"""Вложения MAX (inline_keyboard) для POST /messages и POST /answers."""

from __future__ import annotations


def cb_btn(text: str, payload: str) -> dict:
    return {"type": "callback", "text": text, "payload": payload, "intent": "default"}


def link_btn(text: str, url: str) -> dict:
    return {"type": "link", "text": text, "url": url}


def inline_keyboard(button_rows: list[list[dict]]) -> list[dict]:
    return [{"type": "inline_keyboard", "payload": {"buttons": button_rows}}]


def request_contact_btn(text: str = "📱 Поделиться контактом") -> dict:
    return {"type": "request_contact", "text": text}


def phone_input_keyboard() -> list[dict]:
    """Шаг телефона: кнопка контакта MAX + назад в меню."""
    return inline_keyboard(
        [
            [request_contact_btn()],
            [cb_btn("🔙 В главное меню", "main_menu")],
        ]
    )
