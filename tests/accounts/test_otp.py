from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import OtpChallenge

pytestmark = pytest.mark.django_db


@pytest.fixture
def challenge(api_client, inbox):
    response = api_client.post(
        "/api/v1/auth/organizations",
        {
            "organization_name": "Party",
            "admin_name": "Signer",
            "email": "signer@party.example",
            "phone": "+2348030000001",
            "password": "correct-horse-battery-staple",
            "otp_channel": "SMS",
        },
        format="json",
    )
    return response.json()["challenge_id"]


def _verify(api_client, challenge_id, code):
    return api_client.post(
        "/api/v1/auth/otp/verify", {"challenge_id": challenge_id, "code": code}, format="json"
    )


def test_code_is_stored_hashed(challenge, inbox):
    stored = OtpChallenge.objects.get(id=challenge)
    assert inbox.last_code() not in stored.code_hash
    assert len(stored.code_hash) == 64


def test_five_wrong_attempts_burn_the_challenge(api_client, challenge, inbox):
    code = inbox.last_code()
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        assert _verify(api_client, challenge, wrong).json()["code"] == "otp_invalid"
    assert OtpChallenge.objects.get(id=challenge).attempts == 5
    # The right code no longer works either.
    assert _verify(api_client, challenge, code).json()["code"] == "otp_invalid"


def test_expired_code(api_client, challenge, inbox):
    OtpChallenge.objects.filter(id=challenge).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    assert _verify(api_client, challenge, inbox.last_code()).json()["code"] == "otp_invalid"


def test_code_is_single_use(api_client, challenge, inbox):
    code = inbox.last_code()
    assert _verify(api_client, challenge, code).status_code == 200
    assert _verify(api_client, challenge, code).json()["code"] == "otp_invalid"


def test_resend_cooldown_and_new_code(api_client, challenge, inbox):
    first = inbox.last_code()
    response = api_client.post(
        "/api/v1/auth/otp/request", {"challenge_id": challenge}, format="json"
    )
    assert response.json()["code"] == "otp_resend_too_soon"

    OtpChallenge.objects.filter(id=challenge).update(
        last_sent_at=timezone.now() - timedelta(seconds=61)
    )
    response = api_client.post(
        "/api/v1/auth/otp/request", {"challenge_id": challenge}, format="json"
    )
    assert response.status_code == 202
    second = inbox.last_code()
    assert len(inbox.messages()) == 2
    if second != first:
        assert _verify(api_client, challenge, first).json()["code"] == "otp_invalid"
    assert _verify(api_client, challenge, second).status_code == 200


def test_resend_for_unknown_challenge_looks_the_same(api_client):
    response = api_client.post(
        "/api/v1/auth/otp/request",
        {"challenge_id": "0190a6a0-0000-7000-8000-000000000000"},
        format="json",
    )
    assert response.status_code == 202


def test_hourly_budget_per_destination(api_client, challenge, settings):
    settings.VTRS_OTP_HOURLY_PER_DESTINATION = 1  # the registration already spent it
    OtpChallenge.objects.filter(id=challenge).update(
        last_sent_at=timezone.now() - timedelta(seconds=61)
    )
    response = api_client.post(
        "/api/v1/auth/otp/request", {"challenge_id": challenge}, format="json"
    )
    assert response.status_code == 429
    assert response.json()["code"] == "otp_budget_exceeded"


def test_sms_only_to_allowed_countries(api_client):
    response = api_client.post(
        "/api/v1/auth/organizations",
        {
            "organization_name": "Party",
            "admin_name": "Signer",
            "email": "uk@party.example",
            "phone": "+447700900123",
            "password": "correct-horse-battery-staple",
            "otp_channel": "SMS",
        },
        format="json",
    )
    assert response.status_code == 400
    assert response.json()["code"] == "sms_destination_not_allowed"


def test_malformed_code_is_a_validation_error(api_client, challenge):
    response = _verify(api_client, challenge, "12ab")
    assert response.json()["code"] == "validation_error"
