"""Вложения MAX (inline_keyboard) для POST /messages и POST /answers."""

from __future__ import annotations


def cb_btn(text: str, payload: str) -> dict:
    return {"type": "callback", "text": text, "payload": payload, "intent": "default"}


def link_btn(text: str, url: str) -> dict:
    return {"type": "link", "text": text, "url": url}


def inline_keyboard(button_rows: list[list[dict]]) -> list[dict]:
    return [{"type": "inline_keyboard", "payload": {"buttons": button_rows}}]
