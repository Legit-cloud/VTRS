from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import Device, RefreshToken, Session, User
from apps.audit.models import AuditEvent
from apps.core.domain.permissions import Role

from ..conftest import PASSWORD

pytestmark = pytest.mark.django_db


def _login(api, identifier, password=PASSWORD, **extra):
    return api.post(
        "/api/v1/auth/login",
        {"identifier": identifier, "password": password, **extra},
        format="json",
    )


def _bearer(client, token):
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def test_login_by_email_or_phone(api_client, make_member):
    member = make_member(Role.WARD_OFFICER)
    for identifier in (member.email.upper(), member.phone, "0" + member.phone[4:]):
        body = _login(api_client, identifier).json()
        assert body["mfa_required"] is False, identifier
        assert body["mfa_enrolment_required"] is False
        assert body["token_type"] == "Bearer"


def test_unknown_user_and_wrong_password_look_identical(api_client, make_member):
    member = make_member()
    unknown = _login(api_client, "ghost@example.org")
    wrong = _login(api_client, member.email, "wrong-password-123")
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["code"] == wrong.json()["code"] == "invalid_credentials"
    assert unknown.json()["detail"] == wrong.json()["detail"]


def test_progressive_lockout(api_client, make_member):
    member = make_member()
    for _ in range(5):
        _login(api_client, member.email, "wrong-password-123")
    user = User.objects.get(id=member.user.id)
    assert user.failed_login_count == 5
    assert user.locked_until > timezone.now()
    # Locked: even the right password fails, with the same answer.
    assert _login(api_client, member.email).json()["code"] == "invalid_credentials"

    User.objects.filter(id=user.id).update(locked_until=timezone.now() - timedelta(seconds=1))
    assert _login(api_client, member.email).status_code == 200
    assert User.objects.get(id=user.id).failed_login_count == 0
    assert AuditEvent.objects.filter(action="auth.sign_in_failed").count() == 5


def test_login_throttle_per_ip(api_client, make_member, settings):
    settings.VTRS_THROTTLE_RATES = {**settings.VTRS_THROTTLE_RATES, "login_ip": "2/min"}
    member = make_member()
    assert _login(api_client, member.email).status_code == 200
    assert _login(api_client, member.email).status_code == 200
    response = _login(api_client, member.email)
    assert response.status_code == 429
    assert response.json()["code"] == "throttled"
    assert "Retry-After" in response


def test_refresh_rotates_and_detects_reuse(api_client, make_member):
    member = make_member(Role.WARD_OFFICER)
    first = _login(api_client, member.email).json()

    rotated = api_client.post(
        "/api/v1/auth/refresh", {"refresh_token": first["refresh_token"]}, format="json"
    )
    assert rotated.status_code == 200
    second = rotated.json()
    assert second["refresh_token"] != first["refresh_token"]
    assert second["session_id"] == first["session_id"]

    # Replaying the old refresh token revokes the whole session...
    replay = api_client.post(
        "/api/v1/auth/refresh", {"refresh_token": first["refresh_token"]}, format="json"
    )
    assert replay.json()["code"] == "invalid_refresh_token"
    assert Session.objects.get(id=first["session_id"]).revoke_reason == "refresh_token_reuse"
    assert AuditEvent.objects.filter(action="auth.refresh_token_reused").exists()

    # ...including the token the legitimate holder got, and its access token.
    after = api_client.post(
        "/api/v1/auth/refresh", {"refresh_token": second["refresh_token"]}, format="json"
    )
    assert after.json()["code"] == "invalid_refresh_token"
    me = _bearer(api_client, second["access_token"]).get("/api/v1/me")
    assert me.json()["code"] == "token_revoked"


def test_refresh_tokens_are_stored_hashed(api_client, make_member):
    member = make_member(Role.WARD_OFFICER)
    token = _login(api_client, member.email).json()["refresh_token"]
    assert not RefreshToken.objects.filter(token_hash=token).exists()


def test_web_sessions_do_not_slide(api_client, make_member):
    member = make_member(Role.WARD_OFFICER)
    first = _login(api_client, member.email).json()
    rotated = api_client.post(
        "/api/v1/auth/refresh", {"refresh_token": first["refresh_token"]}, format="json"
    ).json()
    assert rotated["refresh_expires_at"] == first["refresh_expires_at"]

    Session.objects.filter(id=first["session_id"]).update(expires_at=timezone.now())
    expired = api_client.post(
        "/api/v1/auth/refresh", {"refresh_token": rotated["refresh_token"]}, format="json"
    )
    assert expired.json()["code"] == "invalid_refresh_token"


def test_agents_must_sign_in_from_their_registered_device(api_client, make_member):
    agent = make_member(Role.PU_AGENT)
    device = Device.objects.create(user=agent.user, platform="ANDROID", app_version="1.0.0")

    assert (
        _login(api_client, agent.phone, client="MOBILE").json()["code"] == "device_not_registered"
    )
    ok = _login(api_client, agent.phone, client="MOBILE", device_id=str(device.id))
    assert ok.status_code == 200

    # Refresh is bound to the device too, and mobile sessions slide.
    tokens = ok.json()
    stolen = api_client.post(
        "/api/v1/auth/refresh", {"refresh_token": tokens["refresh_token"]}, format="json"
    )
    assert stolen.json()["code"] == "invalid_refresh_token"
    fresh = _login(api_client, agent.phone, client="MOBILE", device_id=str(device.id)).json()
    rotated = api_client.post(
        "/api/v1/auth/refresh",
        {"refresh_token": fresh["refresh_token"], "device_id": str(device.id)},
        format="json",
    )
    assert rotated.status_code == 200
    assert rotated.json()["refresh_expires_at"] >= fresh["refresh_expires_at"]


def test_logout_kills_the_access_token_immediately(api_client, make_member):
    member = make_member(Role.WARD_OFFICER)
    tokens = _login(api_client, member.email).json()
    client = _bearer(api_client, tokens["access_token"])
    assert client.get("/api/v1/me").status_code == 200
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/me").json()["code"] == "token_revoked"


def test_bumping_session_version_revokes_every_token(api_client, make_member):
    member = make_member(Role.WARD_OFFICER)
    tokens = _login(api_client, member.email).json()
    User.objects.filter(id=member.user.id).update(session_version=99)
    response = _bearer(api_client, tokens["access_token"]).get("/api/v1/me")
    assert response.json()["code"] == "token_revoked"


@pytest.mark.parametrize(
    "header",
    ["Bearer", "Bearer a b", "Bearer not.a.jwt", "Bearer eyJhbGciOiJub25lIn0.eyJzdWIiOiIxIn0."],
)
def test_malformed_tokens(api_client, header):
    api_client.credentials(HTTP_AUTHORIZATION=header)
    response = api_client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_token"


def test_token_from_another_key_is_rejected(api_client, make_member, token_for, settings):
    member = make_member(Role.WARD_OFFICER)
    token = token_for(member)
    from config.settings.local_keys import _ephemeral_jwt_key

    settings.VTRS_JWT_PRIVATE_KEY = _ephemeral_jwt_key()
    response = _bearer(api_client, token).get("/api/v1/me")
    assert response.json()["code"] == "invalid_token"


def test_retired_key_still_verifies_during_rotation(api_client, make_member, token_for, settings):
    from cryptography.hazmat.primitives import serialization

    from apps.accounts.tokens import _private_key

    member = make_member(Role.WARD_OFFICER)
    token = token_for(member)
    old_public = (
        _private_key(settings.VTRS_JWT_PRIVATE_KEY)
        .public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    from config.settings.local_keys import _ephemeral_jwt_key

    settings.VTRS_JWT_PUBLIC_KEYS = {"k1": old_public}
    settings.VTRS_JWT_PRIVATE_KEY = _ephemeral_jwt_key()
    settings.VTRS_JWT_KEY_ID = "k2"
    assert _bearer(api_client, token).get("/api/v1/me").status_code == 200


def test_non_object_bodies_are_validation_errors(api_client):
    # Used to reach the per-account throttle, which assumed a JSON object.
    response = api_client.post("/api/v1/auth/login", ["identifier", "password"], format="json")
    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"


def test_old_app_versions_must_upgrade(api_client):
    response = api_client.get(
        "/api/v1/health/live", HTTP_X_APP_PLATFORM="android", HTTP_X_APP_VERSION="0.9.9"
    )
    assert response.status_code == 426
    assert response.json()["code"] == "upgrade_required"
    ok = api_client.get(
        "/api/v1/health/live", HTTP_X_APP_PLATFORM="android", HTTP_X_APP_VERSION="1.0.0"
    )
    assert ok.status_code == 200
    assert api_client.get("/api/v1/health/live").status_code == 200  # web: no header
