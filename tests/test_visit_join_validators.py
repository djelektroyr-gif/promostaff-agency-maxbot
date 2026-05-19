from __future__ import annotations

import visit_join_validators as v


def test_validate_join_phone_mobile_rf_rejects_non_mobile():
    assert v.validate_join_phone_mobile_rf("+7 916 123-45-67") == "+79161234567"
    assert v.validate_join_phone_mobile_rf("+7 495 123-45-67") is None


def test_validate_inn_digits_requires_checksum():
    assert v.validate_inn_digits("7707083893")
    assert not v.validate_inn_digits("7707083894")


def test_validate_join_full_name_matches_telegram_rules():
    assert v.validate_join_full_name("Иванов Иван Иванович")
    assert not v.validate_join_full_name("Иван Иван")


def test_validate_medbook_expiry_rejects_past_date():
    assert v.validate_medbook_expiry("31.12.2030") is not None
    assert v.validate_medbook_expiry("01.01.2000") is None


def test_join_validation_error_codes_have_stable_texts():
    assert v.join_validation_error_text("inn_invalid")
    assert v.join_validation_error_text("full_name_invalid")
    assert "Проверьте" in v.join_validation_error_text("unknown_code")
