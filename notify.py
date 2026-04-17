"""
Уведомления администраторам: SMTP (письма) и MAX (личные сообщения бота).

Вызывайте `notify_agency_admins` из сценариев (например, новые расчёты цен, отклики),
когда бизнес-логика будет готова. Пока модуль только отправляет, если переменные заданы.
"""
from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Iterable

from config import (
    ADMIN_MAX_USER_IDS,
    MAX_TOKEN,
    NOTIFY_EMAIL_TO,
    SMTP_FROM,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USE_TLS,
    SMTP_USER,
)
from max_client import post_message

logger = logging.getLogger(__name__)


def smtp_configured() -> bool:
    return bool(SMTP_HOST and SMTP_FROM and NOTIFY_EMAIL_TO)


def _smtp_send_sync(subject: str, body: str, recipients: Iterable[str]) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)

    # Таймаут на соединение: иначе при недоступной сети сокет может висеть очень долго.
    _smtp_timeout = 30.0

    if SMTP_PORT == 465:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(
            SMTP_HOST, SMTP_PORT, context=context, timeout=_smtp_timeout
        ) as server:
            if SMTP_USER and SMTP_PASSWORD:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        return

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
        if SMTP_USE_TLS:
            server.starttls(context=ssl.create_default_context())
        if SMTP_USER and SMTP_PASSWORD:
            server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)


async def send_admin_email(subject: str, body: str) -> bool:
    if not smtp_configured():
        return False
    recipients = [x.strip() for x in NOTIFY_EMAIL_TO.replace(";", ",").split(",") if x.strip()]
    if not recipients:
        return False

    def _run() -> None:
        _smtp_send_sync(subject, body, recipients)

    try:
        await asyncio.to_thread(_run)
        return True
    except Exception:
        logger.exception("SMTP notify failed")
        return False


async def send_admin_max_messages(text: str) -> int:
    if not MAX_TOKEN or not ADMIN_MAX_USER_IDS:
        return 0
    n = 0
    for uid in ADMIN_MAX_USER_IDS:
        ok = await post_message(MAX_TOKEN, uid, {"text": text})
        if ok:
            n += 1
    return n


async def notify_agency_admins(subject: str, body: str) -> dict[str, int | bool]:
    """
    Дублирует текст на почту (если настроен SMTP) и в MAX указанным user_id.

    Возвращает счётчики для логов/дашборда; ошибки не пробрасываются.
    """
    email_ok = await send_admin_email(subject, body)
    max_n = await send_admin_max_messages(f"{subject}\n\n{body}")
    return {"email_sent": bool(email_ok), "max_messages": max_n}
