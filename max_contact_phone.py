"""Разбор контакта из сообщения MAX (кнопка request_contact)."""
from __future__ import annotations

import hashlib
import hmac
import logging
import re

from config import MAX_TOKEN

logger = logging.getLogger(__name__)

_TEL_RE = re.compile(r"TEL[^:]*:([+\d]+)", re.IGNORECASE)


def _normalize_vcf_for_hash(vcf_info: str) -> bytes:
    """Перед HMAC: литералы \\r\\n в строке → реальные переносы (документация MAX)."""
    return vcf_info.replace("\\r\\n", "\r\n").replace("\\n", "\n").encode("utf-8")


def verify_contact_hash(vcf_info: str, received_hash: str) -> bool:
    token = (MAX_TOKEN or "").strip()
    if not token or not vcf_info or not received_hash:
        return False
    expected = hmac.new(
        token.encode("utf-8"),
        _normalize_vcf_for_hash(vcf_info),
        hashlib.sha256,
    ).hexdigest()
    try:
        return hmac.compare_digest(expected, str(received_hash).strip())
    except Exception:
        return False


def phone_from_vcf(vcf_info: str) -> str | None:
    if not vcf_info:
        return None
    m = _TEL_RE.search(vcf_info)
    if not m:
        return None
    return m.group(1).strip()


def contact_from_message_body(message_body: dict | None) -> tuple[str | None, bool]:
    """
    (номер для validate_join_phone / validate_phone, verified).
    verified=True только если hash совпал с vcf_info (кнопка request_contact).
    """
    if not message_body:
        return None, False
    raw = message_body.get("attachments")
    if raw is None and isinstance(message_body.get("attachment"), dict):
        raw = [message_body["attachment"]]
    if not isinstance(raw, list):
        return None, False
    for a in raw:
        if not isinstance(a, dict):
            continue
        if (a.get("type") or "").lower() != "contact":
            continue
        p = a.get("payload")
        if not isinstance(p, dict):
            continue
        vcf = str(p.get("vcf_info") or "")
        ph = phone_from_vcf(vcf)
        if not ph:
            max_info = p.get("max_info")
            if isinstance(max_info, dict):
                for key in ("phone", "mobile", "tel"):
                    v = max_info.get(key)
                    if v:
                        ph = str(v).strip()
                        break
        if not ph:
            continue
        h = str(p.get("hash") or "")
        verified = bool(h and verify_contact_hash(vcf, h))
        return ph, verified
    return None, False
