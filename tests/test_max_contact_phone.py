"""Разбор контакта MAX (request_contact)."""
import hashlib
import hmac

from max_contact_phone import (
    contact_from_message_body,
    phone_from_vcf,
    verify_contact_hash,
)


def test_phone_from_vcf_ru_cell():
    vcf = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\n"
        "TEL;TYPE=cell:79991234567\r\n"
        "FN:Ivan Ivanov\r\nEND:VCARD\r\n"
    )
    assert phone_from_vcf(vcf) == "79991234567"


def test_verify_contact_hash_matches_docs_example(monkeypatch):
    token = "secret"
    monkeypatch.setattr("max_contact_phone.MAX_TOKEN", token)
    vcf = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\n"
        "TEL;TYPE=cell:79990000000\r\nFN:Ivan Ivanov\r\nEND:VCARD\r\n"
    )
    expected = hmac.new(
        token.encode("utf-8"),
        vcf.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    assert verify_contact_hash(vcf, expected) is True


def test_contact_from_message_body():
    body = {
        "attachments": [
            {
                "type": "contact",
                "payload": {
                    "vcf_info": "BEGIN:VCARD\r\nTEL;TYPE=cell:79161234567\r\nEND:VCARD\r\n",
                    "hash": "skip",
                },
            }
        ]
    }
    ph, verified = contact_from_message_body(body)
    assert ph == "79161234567"
    assert verified is False
