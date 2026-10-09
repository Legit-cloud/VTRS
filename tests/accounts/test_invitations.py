"""AC-03 / AC-04 (server side): invite an agent to polling units; the agent activates on a
registered device and sees only that assignment."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import Device, Invitation, Membership
from apps.core.domain.permissions import Role
from apps.core.rls import system_context
from apps.geography.domain.synthetic import synthetic_master_data
from apps.geography.models import PollingUnit, Ward
from apps.geography.services import import_master_data

pytestmark = pytest.mark.django_db
AGENT_PHONE = "08035550001"
DEVICE = {"platform": "ANDROID", "app_version": "1.2.0", "public_key": "pk", "push_token": "fcm"}


@pytest.fixture
def geography():
    import_master_data(synthetic_master_data(lgas=2, wards=4, polling_units=12))


@pytest.fixture
def admin(make_member):
    return make_member(Role.PARTY_ADMIN)


@pytest.fixture
def admin_client(admin, client_as):
    return client_as(admin)


def _invite(client, key="inv-1", **body):
    return client.post("/api/v1/invitations", body, format="json", HTTP_IDEMPOTENCY_KEY=key)


def _agent_invite(client, pu_ids, key="inv-1"):
    return _invite(
        client,
        key=key,
        role="PU_AGENT",
        scope_ids=[str(i) for i in pu_ids],
        full_name="Agent One",
        phone=AGENT_PHONE,
    )


def _accept(client, inbox, device=DEVICE):
    token = inbox.last_invitation_token("+2348035550001")
    started = client.post("/api/v1/auth/invitations/accept", {"token": token}, format="json").json()
    assert started["destination_hint"] == "***********001"
    return client.post(
        "/api/v1/auth/invitations/complete",
        {
            "token": token,
            "challenge_id": started["challenge_id"],
            "code": inbox.last_code("+2348035550001"),
            "password": "agent-strong-passphrase",
            "device": device,
        },
        format="json",
    )


def test_agent_onboarding_end_to_end(geography, admin, admin_client, api_client, inbox):
    pus = list(PollingUnit.objects.order_by("inec_code")[:2].values_list("id", flat=True))
    response = _agent_invite(admin_client, pus)
    assert response.status_code == 201, response.json()
    assert response.json()["status"] == "PENDING"
    assert response.json()["phone"] == "***********001"  # masked in the API
    assert "token" not in str(response.json())

    activated = _accept(api_client, inbox)
    assert activated.status_code == 200, activated.json()
    tokens = activated.json()

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access_token']}")
    me = api_client.get("/api/v1/me").json()
    assert me["role"] == "PU_AGENT"
    assert me["scope"] == {"type": "PU", "ids": sorted(str(i) for i in pus)}
    assert "results.submit" in me["permissions"]
    assert me["organization"]["id"] == str(admin.organization.id)

    device = Device.objects.get(user_id=me["user_id"])
    assert (device.platform, device.app_version, device.status) == ("ANDROID", "1.2.0", "ACTIVE")

    # The agent can sign in again only from that device.
    login = api_client.post(
        "/api/v1/auth/login",
        {
            "identifier": AGENT_PHONE,
            "password": "agent-strong-passphrase",
            "client": "MOBILE",
            "device_id": str(device.id),
        },
        format="json",
    )
    assert login.status_code == 200

    # Agents cannot manage the team.
    assert api_client.get("/api/v1/users").json()["code"] == "forbidden"


def test_invitation_token_is_single_use(geography, admin_client, api_client, inbox):
    _agent_invite(admin_client, PollingUnit.objects.values_list("id", flat=True)[:1])
    assert _accept(api_client, inbox).status_code == 200
    token = inbox.last_invitation_token()
    response = api_client.post("/api/v1/auth/invitations/accept", {"token": token}, format="json")
    assert response.json()["code"] == "invitation_invalid"


def test_expired_and_revoked_invitations(geography, admin_client, api_client, inbox):
    pu = PollingUnit.objects.values_list("id", flat=True)[:1]
    invitation_id = _agent_invite(admin_client, pu).json()["id"]
    Invitation.objects.filter(id=invitation_id).update(
        expires_at=timezone.now() - timedelta(minutes=1)
    )
    token = inbox.last_invitation_token()
    expired = api_client.post("/api/v1/auth/invitations/accept", {"token": token}, format="json")
    assert expired.json()["code"] == "invitation_invalid"

    Invitation.objects.filter(id=invitation_id).update(
        expires_at=timezone.now() + timedelta(days=1)
    )
    revoked = admin_client.post(
        f"/api/v1/invitations/{invitation_id}/revoke", HTTP_IDEMPOTENCY_KEY="rev-1"
    )
    assert revoked.json()["status"] == "REVOKED"
    response = api_client.post("/api/v1/auth/invitations/accept", {"token": token}, format="json")
    assert response.json()["code"] == "invitation_invalid"
    assert (
        api_client.post(
            "/api/v1/auth/invitations/accept", {"token": "made-up"}, format="json"
        ).json()["code"]
        == "invitation_invalid"
    )


def test_otp_from_another_invitation_does_not_work(geography, admin_client, api_client, inbox):
    pus = list(PollingUnit.objects.values_list("id", flat=True)[:2])
    _agent_invite(admin_client, pus[:1], key="a")
    token_a = inbox.last_invitation_token()
    _invite(admin_client, key="b", role="PU_AGENT", scope_ids=[str(pus[1])], phone="08035550002")
    token_b = inbox.last_invitation_token("+2348035550002")
    challenge_b = api_client.post(
        "/api/v1/auth/invitations/accept", {"token": token_b}, format="json"
    ).json()["challenge_id"]
    response = api_client.post(
        "/api/v1/auth/invitations/complete",
        {
            "token": token_a,
            "challenge_id": challenge_b,
            "code": inbox.last_code("+2348035550002"),
            "password": "agent-strong-passphrase",
            "device": DEVICE,
        },
        format="json",
    )
    assert response.json()["code"] == "invitation_invalid"


def test_agents_must_register_a_device(geography, admin_client, api_client, inbox):
    _agent_invite(admin_client, PollingUnit.objects.values_list("id", flat=True)[:1])
    response = _accept(api_client, inbox, device=None)
    assert response.status_code == 400
    assert "device" in response.json()["errors"]


def test_ward_officer_invited_by_email(geography, admin_client, api_client, inbox):
    ward = Ward.objects.first()
    response = _invite(
        admin_client,
        role="WARD_OFFICER",
        scope_ids=[str(ward.id)],
        granted_permissions=["evidence.view"],
        email="ward.officer@party.example",
    )
    assert response.status_code == 201
    token = inbox.last_invitation_token("ward.officer@party.example")
    started = api_client.post(
        "/api/v1/auth/invitations/accept", {"token": token}, format="json"
    ).json()
    assert started["channel"] == "EMAIL"
    done = api_client.post(
        "/api/v1/auth/invitations/complete",
        {
            "token": token,
            "challenge_id": started["challenge_id"],
            "code": inbox.last_code("ward.officer@party.example"),
            "password": "ward-strong-passphrase",
        },
        format="json",
    )
    assert done.status_code == 200
    with system_context():
        membership = Membership.objects.get(role="WARD_OFFICER")
    assert membership.scope_ids == [ward.id]
    assert membership.granted_permissions == ["evidence.view"]


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"role": "PU_AGENT", "scope_ids": [], "phone": AGENT_PHONE}, "scope_ids"),
        (
            {
                "role": "PU_AGENT",
                "scope_ids": ["0190a6a0-0000-7000-8000-000000000000"],
                "phone": AGENT_PHONE,
            },
            "scope_ids",
        ),
        ({"role": "PU_AGENT", "email": "a@b.org"}, "scope_ids"),
        (
            {
                "role": "PARTY_ADMIN",
                "scope_ids": ["0190a6a0-0000-7000-8000-000000000000"],
                "email": "x@y.org",
            },
            "scope_ids",
        ),
        (
            {
                "role": "WARD_OFFICER",
                "scope_ids": [],
                "email": "x@y.org",
                "granted_permissions": ["evidence.export"],
            },
            "scope_ids",
        ),
    ],
)
def test_invalid_invitations(geography, admin_client, body, field):
    response = _invite(admin_client, **body)
    assert response.status_code == 400
    assert field in response.json()["errors"]


def test_grants_beyond_the_role_are_refused(geography, admin_client):
    ward = Ward.objects.first()
    response = _invite(
        admin_client,
        role="WARD_OFFICER",
        scope_ids=[str(ward.id)],
        granted_permissions=["evidence.export"],
        email="x@y.org",
    )
    assert response.json()["errors"] == {
        "granted_permissions": ["Not grantable to WARD_OFFICER: ['evidence.export']"]
    }


def test_contact_already_in_use(geography, admin, admin_client):
    response = _invite(admin_client, role="PARTY_ADMIN", email=admin.email)
    assert response.status_code == 409
    assert response.json()["code"] == "contact_in_use"


def test_invitation_create_is_idempotent(geography, admin_client, inbox):
    pus = PollingUnit.objects.values_list("id", flat=True)[:1]
    first = _agent_invite(admin_client, pus, key="same")
    again = _agent_invite(admin_client, pus, key="same")
    assert first.json() == again.json()
    assert again["Idempotent-Replayed"] == "true"
    assert Invitation.objects.count() == 1
    assert len(inbox.messages()) == 1  # no second SMS

    missing = admin_client.post("/api/v1/invitations", {"role": "PARTY_ADMIN"}, format="json")
    assert missing.json()["code"] == "invalid_idempotency_key"
