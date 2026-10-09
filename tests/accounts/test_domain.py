from datetime import timedelta

import pytest

from apps.accounts.domain.codes import (
    generate_otp,
    generate_token,
    hash_otp,
    hash_token,
    otp_matches,
)
from apps.accounts.domain.contact import (
    is_allowed_sms_destination,
    mask_email,
    mask_phone,
    normalize_email,
    normalize_phone,
)
from apps.accounts.domain.lockout import lockout_for


@pytest.mark.parametrize(
    "raw",
    [
        "08031234567",
        "+2348031234567",
        "2348031234567",
        "002348031234567",
        "0803 123 4567",
        "(0803)-123-4567",
    ],
)
def test_nigerian_numbers_normalize_to_e164(raw):
    assert normalize_phone(raw) == "+2348031234567"


@pytest.mark.parametrize("raw", ["", "abc", "0803123", "+23480312345678", "+234 803 123 456"])
def test_invalid_phone_numbers(raw):
    with pytest.raises(ValueError):
        normalize_phone(raw)


def test_foreign_numbers_pass_normalization_but_not_the_sms_allow_list():
    phone = normalize_phone("+447700900123")
    assert phone == "+447700900123"
    assert not is_allowed_sms_destination(phone, ["+234"])
    assert is_allowed_sms_destination("+2348031234567", ["+234"])


def test_email_normalization():
    assert normalize_email("  Ada@Example.ORG ") == "ada@example.org"
    with pytest.raises(ValueError):
        normalize_email("not-an-email")


def test_masking():
    assert mask_phone("+2348031234567") == "***********567"
    assert mask_email("ada@example.org") == "a***@example.org"


def test_otp_codes():
    codes = {generate_otp() for _ in range(200)}
    assert all(len(c) == 6 and c.isdigit() for c in codes)
    assert len(codes) > 150  # random, not a counter


def test_otp_hash_is_bound_to_challenge_and_pepper():
    digest = hash_otp(b"pepper", "challenge-1", "123456")
    assert otp_matches(digest, b"pepper", "challenge-1", "123456")
    assert not otp_matches(digest, b"pepper", "challenge-2", "123456")
    assert not otp_matches(digest, b"other", "challenge-1", "123456")
    assert not otp_matches(digest, b"pepper", "challenge-1", "654321")


def test_tokens_are_long_and_stored_as_hashes():
    token = generate_token()
    assert len(token) >= 43  # 256 bits, base64url
    assert hash_token(token) != token
    assert len(hash_token(token)) == 64


@pytest.mark.parametrize(
    ("failures", "expected"),
    [
        (4, None),
        (5, timedelta(minutes=1)),
        (9, timedelta(minutes=1)),
        (10, timedelta(minutes=5)),
        (15, timedelta(minutes=30)),
        (40, timedelta(minutes=30)),
    ],
)
def test_progressive_lockout(failures, expected):
    assert lockout_for(failures) == expected
