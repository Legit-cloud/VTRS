"""AC-01: register an organization, verify by OTP, operator approval; then every sign-in and
every sensitive action needs a code sent to the account's email."""

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.accounts.domain.contact import mask_email
from apps.accounts.models import Membership, OtpChallenge, User, UserStatus
from apps.audit.models import AuditEvent
from apps.core.domain.permissions import Role
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


def _code(api_client, mfa_token, code):
    return api_client.post(
        "/api/v1/auth/login/mfa", {"mfa_token": mfa_token, "code": code}, format="json"
    )


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
    # The password alone is not enough: a code went to the signer's email.
    assert login["mfa_required"] is True
    assert login["destination_hint"] == "a***@party.example"
    assert "access_token" not in login
    tokens = _code(api_client, login["mfa_token"], inbox.last_code("ada@party.example")).json()

    admin = api_client.__class__(api_client._capture)
    admin.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access_token']}")
    me = admin.get("/api/v1/me").json()
    assert (me["role"], me["mfa_required"]) == ("PARTY_ADMIN", True)
    assert "mfa_enabled" not in me
    assert me["email"] == "ada@party.example"
    assert admin.get("/api/v1/users").status_code == 200

    actions = set(AuditEvent.objects.values_list("action", flat=True))
    assert {
        "organization.registered",
        "organization.signer_verified",
        "organization.approved",
        "auth.signed_in",
    } <= actions


@pytest.mark.parametrize("role", list(Role))
def test_every_role_signs_in_with_an_emailed_code(api_client, inbox, make_member, role):
    member = make_member(role)
    first = _login(api_client, member.email).json()
    assert set(first) == {"mfa_required", "mfa_token", "challenge_id", "destination_hint"}
    code = inbox.last_code(member.email)
    assert "sign in to VTRS" in inbox.messages(member.email)[-1]

    ok = _code(api_client, first["mfa_token"], code)
    assert ok.status_code == 200, ok.json()
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {ok.json()['access_token']}")
    assert api_client.get("/api/v1/me").json()["role"] == role
    # Used once only.
    assert _code(api_client, first["mfa_token"], code).json()["code"] == "mfa_invalid"


def test_wrong_codes_run_out(api_client, inbox, make_member):
    member = make_member(Role.PU_AGENT)
    first = _login(api_client, member.email).json()
    code = inbox.last_code(member.email)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        assert _code(api_client, first["mfa_token"], wrong).json()["code"] == "mfa_invalid"
    # After five misses even the right code is refused; the agent signs in again.
    assert _code(api_client, first["mfa_token"], code).json()["code"] == "mfa_invalid"


def test_a_code_only_works_with_its_own_sign_in(api_client, inbox, make_member, client_as):
    alice, bob = make_member(Role.WARD_OFFICER), make_member(Role.WARD_OFFICER)
    alice_login = _login(api_client, alice.email).json()
    _login(api_client, bob.email)
    bob_code = inbox.last_code(bob.email)
    assert _code(api_client, alice_login["mfa_token"], bob_code).json()["code"] == "mfa_invalid"
    assert _code(api_client, "forged", bob_code).json()["code"] == "mfa_invalid"

    # A step-up code is not a sign-in code.
    step = client_as(alice).post("/api/v1/auth/mfa/step-up/request").json()
    step_code = inbox.last_code(alice.email)
    assert step["challenge_id"] != alice_login["challenge_id"]
    assert _code(api_client, alice_login["mfa_token"], step_code).json()["code"] == "mfa_invalid"


def test_signing_in_twice_quickly_sends_one_email(api_client, inbox, make_member):
    member = make_member(Role.PU_AGENT)
    first = _login(api_client, member.email).json()
    second = _login(api_client, member.email).json()
    assert first["challenge_id"] == second["challenge_id"]
    assert len(inbox.messages(member.email)) == 1
    # Either token works with that one code.
    code = inbox.last_code(member.email)
    assert _code(api_client, second["mfa_token"], code).status_code == 200


def test_resend_waits_a_minute(api_client, inbox, make_member):
    member = make_member(Role.PU_AGENT)
    first = _login(api_client, member.email).json()
    resend = {"mfa_token": first["mfa_token"]}
    too_soon = api_client.post("/api/v1/auth/login/mfa/resend", resend, format="json")
    assert too_soon.json()["code"] == "otp_resend_too_soon"

    OtpChallenge.objects.filter(id=first["challenge_id"]).update(
        last_sent_at=timezone.now() - timedelta(minutes=2)
    )
    assert (
        api_client.post("/api/v1/auth/login/mfa/resend", resend, format="json").status_code == 202
    )
    assert len(inbox.messages(member.email)) == 2
    assert _code(api_client, first["mfa_token"], inbox.last_code(member.email)).status_code == 200


def test_an_account_without_email_cannot_get_a_code(api_client, make_member):
    member = make_member(Role.PU_AGENT)
    User.objects.filter(id=member.user.id).update(email="", email_index=None)
    response = _login(api_client, member.phone)
    assert response.status_code == 403
    assert response.json()["code"] == "email_required"


def test_sessions_without_the_code_are_shut_out(make_member, client_as):
    agent = client_as(make_member(Role.PU_AGENT), mfa=False)
    assert agent.get("/api/v1/me").status_code == 200  # to find out who they are
    assert agent.get("/api/v1/me/assignments").json()["code"] == "mfa_required"


def test_development_settings_can_turn_codes_off(api_client, make_member, settings):
    settings.VTRS_ENFORCE_MFA = False
    member = make_member(Role.PU_AGENT)
    body = _login(api_client, member.email).json()
    assert body["mfa_required"] is False
    assert "access_token" in body


def test_step_up_by_email(make_member, client_as, inbox):
    member = make_member()
    client = client_as(member)
    sent = client.post("/api/v1/auth/mfa/step-up/request")
    assert sent.status_code == 202
    body = sent.json()
    assert body["destination_hint"] == mask_email(member.email)
    assert "confirm a change in VTRS" in inbox.messages(member.email)[-1]

    wrong = client.post(
        "/api/v1/auth/mfa/step-up",
        {"challenge_id": body["challenge_id"], "code": "12345"},
        format="json",
    )
    assert wrong.status_code == 400
    ok = client.post(
        "/api/v1/auth/mfa/step-up",
        {"challenge_id": body["challenge_id"], "code": inbox.last_code(member.email)},
        format="json",
    )
    assert ok.status_code == 200, ok.json()
    assert ok.json()["access_token"]
    assert AuditEvent.objects.filter(action="auth.mfa_step_up").count() == 1


def test_someone_elses_step_up_code_does_not_work(make_member, client_as, inbox):
    alice = make_member()
    bob = make_member(organization=alice.organization)
    body = client_as(bob).post("/api/v1/auth/mfa/step-up/request").json()
    stolen = client_as(alice).post(
        "/api/v1/auth/mfa/step-up",
        {"challenge_id": body["challenge_id"], "code": inbox.last_code(bob.email)},
        format="json",
    )
    assert stolen.json()["code"] == "mfa_invalid"


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
