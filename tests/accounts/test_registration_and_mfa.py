"""AC-01: register an organization, verify by OTP, operator approval, admin MFA enrolment."""

import pytest
from django.core.management import call_command
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts.models import Membership, User, UserStatus
from apps.audit.models import AuditEvent
from apps.core.rls import system_context
from apps.organizations.models import Organization, OrganizationStatus

from ..conftest import PASSWORD

pytestmark = pytest.mark.django_db

REGISTRATION = {
    "organization_name": "Progressive Party",
    "admin_name": "Ada Signer",
    "email": "ada@party.example",
    "phone": "08031230000",
    "password": PASSWORD,
    "otp_channel": "SMS",
}


def _register(api_client, **overrides):
    return api_client.post(
        "/api/v1/auth/organizations", {**REGISTRATION, **overrides}, format="json"
    )


def _login(api_client, identifier="ada@party.example", password=PASSWORD):
    return api_client.post(
        "/api/v1/auth/login", {"identifier": identifier, "password": password}, format="json"
    )


def _current_totp(user_id):
    device = TOTPDevice.objects.get(user_id=user_id)
    return f"{totp(device.bin_key, step=device.step, digits=device.digits):06d}"


def test_full_registration_flow(api_client, inbox):
    response = _register(api_client)
    assert response.status_code == 201, response.json()
    org_id, challenge_id = response.json()["organization_id"], response.json()["challenge_id"]

    # The OTP went to the signer's phone (normalized), not anywhere else.
    code = inbox.last_code("+2348031230000")
    with system_context():
        assert Organization.objects.get(id=org_id).status == OrganizationStatus.PENDING_VERIFICATION
        user = Membership.objects.get(organization_id=org_id).user
    assert user.status == UserStatus.PENDING_VERIFICATION
    assert _login(api_client).json()["code"] == "account_not_active"

    response = api_client.post(
        "/api/v1/auth/otp/verify", {"challenge_id": challenge_id, "code": code}, format="json"
    )
    assert response.status_code == 200
    assert response.json()["organization_status"] == "PENDING_APPROVAL"

    # Verified, but not yet approved by a platform operator.
    assert _login(api_client).json()["code"] == "organization_not_active"

    call_command("approve_organization", org_id, "--operator", "ops@vtrs")
    login = _login(api_client).json()
    assert login["mfa_required"] is False
    assert login["mfa_enrolment_required"] is True  # admins must enrol MFA

    admin = api_client.__class__(api_client._capture)
    admin.credentials(HTTP_AUTHORIZATION=f"Bearer {login['access_token']}")
    me = admin.get("/api/v1/me").json()
    assert (me["role"], me["mfa_required"], me["mfa_enabled"]) == ("PARTY_ADMIN", True, False)
    assert me["email"] == "ada@party.example"

    # Privileged endpoints refuse until a second factor is enrolled.
    assert admin.get("/api/v1/users").json()["code"] == "mfa_required"

    setup = admin.post("/api/v1/auth/mfa/totp/setup").json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/")
    confirm = admin.post(
        "/api/v1/auth/mfa/totp/confirm", {"code": _current_totp(user.id)}, format="json"
    ).json()
    assert len(confirm["recovery_codes"]) == 10

    admin.credentials(HTTP_AUTHORIZATION=f"Bearer {confirm['access_token']}")
    assert admin.get("/api/v1/users").status_code == 200

    actions = set(AuditEvent.objects.values_list("action", flat=True))
    assert {
        "organization.registered",
        "organization.signer_verified",
        "organization.approved",
        "auth.signed_in",
        "auth.mfa_enrolled",
    } <= actions


def test_next_login_asks_for_the_second_factor(api_client, inbox, make_member):
    member = make_member(mfa_enabled=True)
    TOTPDevice.objects.create(user=member.user, name="authenticator", confirmed=True)
    first = _login(api_client, member.email).json()
    assert first == {"mfa_required": True, "mfa_token": first["mfa_token"]}

    ok = api_client.post(
        "/api/v1/auth/login/mfa",
        {"mfa_token": first["mfa_token"], "code": _current_totp(member.user.id)},
        format="json",
    )
    assert ok.status_code == 200
    assert "access_token" in ok.json()

    wrong = api_client.post(
        "/api/v1/auth/login/mfa", {"mfa_token": first["mfa_token"], "code": "000000"}, format="json"
    )
    assert wrong.json()["code"] == "mfa_invalid"
    # django-otp also throttles the device after a failure, so a guessing run slows down.
    device = TOTPDevice.objects.get(user=member.user)
    assert device.throttling_failure_count == 1


def test_recovery_code_works_once(api_client, make_member, client_as):
    member = make_member()
    client = client_as(member, mfa=False)
    client.post("/api/v1/auth/mfa/totp/setup")
    codes = client.post(
        "/api/v1/auth/mfa/totp/confirm",
        {"code": _current_totp(member.user.id)},
        format="json",
    ).json()["recovery_codes"]

    first = _login(api_client, member.email).json()
    use = {"mfa_token": first["mfa_token"], "code": codes[0].lower()}
    assert api_client.post("/api/v1/auth/login/mfa", use, format="json").status_code == 200
    again = api_client.post("/api/v1/auth/login/mfa", use, format="json")
    assert again.json()["code"] == "mfa_invalid"


def test_duplicate_contact_is_rejected(api_client):
    assert _register(api_client).status_code == 201
    response = _register(api_client, phone="08039999999")  # same email
    assert response.status_code == 400
    assert response.json()["errors"]["email"]


def test_weak_password_and_bad_contacts(api_client):
    body = _register(api_client, password="password", email="nope", phone="12").json()
    assert set(body["errors"]) == {"email", "phone"}
    body = _register(api_client, password="password").json()
    assert "password" in body["errors"]
    with system_context():
        assert not User.objects.exists()


def test_unknown_fields_are_rejected(api_client):
    response = _register(api_client, is_admin=True)
    assert response.status_code == 400
    assert response.json()["errors"] == {"is_admin": ["Unknown field."]}


def test_bot_challenge_is_enforced_when_configured(api_client, settings):
    settings.VTRS_BOT_CHALLENGE_PROVIDER = "always_fail"
    response = _register(api_client)
    assert response.status_code == 400
    assert "bot_token" in response.json()["errors"]


def test_email_channel(api_client, inbox):
    response = _register(api_client, otp_channel="EMAIL")
    assert response.status_code == 201
    assert inbox.last_code("ada@party.example")
