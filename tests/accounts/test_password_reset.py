from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import PasswordResetToken, Session

from ..conftest import PASSWORD

pytestmark = pytest.mark.django_db
NEW_PASSWORD = "a-brand-new-long-passphrase"


def _forgot(client, identifier):
    return client.post("/api/v1/auth/password/forgot", {"identifier": identifier}, format="json")


def test_reset_flow_revokes_sessions(api_client, make_member, inbox, token_for):
    member = make_member()
    old_access = token_for(member)

    challenge = _forgot(api_client, member.phone).json()["challenge_id"]
    verified = api_client.post(
        "/api/v1/auth/otp/verify",
        {"challenge_id": challenge, "code": inbox.last_code(member.phone)},
        format="json",
    ).json()
    reset_token = verified["reset_token"]
    assert not PasswordResetToken.objects.filter(token_hash=reset_token).exists()

    response = api_client.post(
        "/api/v1/auth/password/reset",
        {"reset_token": reset_token, "new_password": NEW_PASSWORD},
        format="json",
    )
    assert response.status_code == 204

    login = api_client.post(
        "/api/v1/auth/login", {"identifier": member.email, "password": PASSWORD}, format="json"
    )
    assert login.json()["code"] == "invalid_credentials"
    login = api_client.post(
        "/api/v1/auth/login", {"identifier": member.email, "password": NEW_PASSWORD}, format="json"
    )
    assert login.status_code == 200

    assert (
        not Session.objects.filter(user=member.user, revoked_at__isnull=True)
        .exclude(id=login.json()["session_id"])
        .exists()
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {old_access}")
    assert api_client.get("/api/v1/me").json()["code"] == "token_revoked"

    # Single use.
    again = api_client.post(
        "/api/v1/auth/password/reset",
        {"reset_token": reset_token, "new_password": NEW_PASSWORD + "x"},
        format="json",
    )
    assert again.json()["code"] == "invalid_reset_token"


def test_unknown_account_gets_the_same_response(api_client, inbox):
    response = _forgot(api_client, "ghost@example.org")
    assert response.status_code == 202
    assert "challenge_id" in response.json()
    assert inbox.messages() == []


def test_expired_reset_token(api_client, make_member, inbox):
    member = make_member()
    challenge = _forgot(api_client, member.email).json()["challenge_id"]
    reset_token = api_client.post(
        "/api/v1/auth/otp/verify",
        {"challenge_id": challenge, "code": inbox.last_code(member.email)},
        format="json",
    ).json()["reset_token"]
    PasswordResetToken.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    response = api_client.post(
        "/api/v1/auth/password/reset",
        {"reset_token": reset_token, "new_password": NEW_PASSWORD},
        format="json",
    )
    assert response.json()["code"] == "invalid_reset_token"
