"""FR-6.11.x: team management, privilege rules and immediate effect of changes."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import Device, User, UserStatus
from apps.accounts.services.sessions import start_session
from apps.audit.models import AuditEvent
from apps.core.domain.permissions import Role
from apps.geography.domain.synthetic import synthetic_master_data
from apps.geography.models import Lga, Ward
from apps.geography.services import import_master_data

pytestmark = pytest.mark.django_db


@pytest.fixture
def geography():
    import_master_data(synthetic_master_data(lgas=2, wards=4, polling_units=8))


def _post(client, path, key, body=None):
    return client.post(path, body or {}, format="json", HTTP_IDEMPOTENCY_KEY=key)


def test_list_and_detail_are_masked_and_org_scoped(make_member, client_as):
    admin = make_member()
    officer = make_member(Role.WARD_OFFICER, organization=admin.organization)
    outsider = make_member(Role.WARD_OFFICER)
    client = client_as(admin)

    listed = client.get("/api/v1/users").json()["results"]
    assert {r["user_id"] for r in listed} == {str(admin.user.id), str(officer.user.id)}
    row = next(r for r in listed if r["user_id"] == str(officer.user.id))
    assert row["phone"].endswith(officer.phone[-3:]) and officer.phone not in row["phone"]
    assert "@" in row["email"] and officer.email not in row["email"]

    assert client.get(f"/api/v1/users/{officer.user.id}").status_code == 200
    # Another organization's user does not exist, as far as this admin can tell.
    assert client.get(f"/api/v1/users/{outsider.user.id}").status_code == 404
    assert client.get("/api/v1/users", {"role": "WARD_OFFICER"}).json()["results"][0]["role"] == (
        "WARD_OFFICER"
    )


def test_deactivation_revokes_access_immediately(make_member, client_as, token_for):
    admin = make_member()
    officer = make_member(Role.WARD_OFFICER, organization=admin.organization)
    officer_client = client_as(officer)
    assert officer_client.get("/api/v1/me").status_code == 200

    response = _post(client_as(admin), f"/api/v1/users/{officer.user.id}/deactivate", "d-1")
    assert response.json()["status"] == "DEACTIVATED"
    assert officer_client.get("/api/v1/me").json()["code"] == "token_revoked"
    assert User.objects.get(id=officer.user.id).status == UserStatus.DEACTIVATED
    assert AuditEvent.objects.filter(action="user.deactivated").exists()


def test_last_admin_cannot_be_deactivated(make_member, client_as):
    admin = make_member()
    response = _post(client_as(admin), f"/api/v1/users/{admin.user.id}/deactivate", "d-1")
    assert response.status_code == 409
    assert response.json()["code"] == "last_admin"

    second = make_member(organization=admin.organization)
    assert (
        _post(client_as(admin), f"/api/v1/users/{second.user.id}/deactivate", "d-2").status_code
        == 200
    )


def test_role_change_needs_step_up_and_applies_at_once(
    geography, make_member, client_as, token_for
):
    admin = make_member()
    officer = make_member(Role.WARD_OFFICER, organization=admin.organization)
    officer_client = client_as(officer)
    assert officer_client.get("/api/v1/me").json()["role"] == "WARD_OFFICER"
    lga = Lga.objects.first()
    body = {
        "role": "LGA_OFFICER",
        "scope_ids": [str(lga.id)],
        "granted_permissions": ["evidence.view"],
    }

    # A session whose second factor is older than the step-up window is refused.
    stale = start_session(
        user=admin.user,
        membership=admin.membership,
        client="WEB",
        device=None,
        mfa_at=timezone.now() - timedelta(minutes=30),
        ip=None,
    )
    stale_client = client_as(admin)
    stale_client.credentials(HTTP_AUTHORIZATION=f"Bearer {stale.access_token}")
    refused = stale_client.put(
        f"/api/v1/users/{officer.user.id}/membership",
        body,
        format="json",
        HTTP_IDEMPOTENCY_KEY="m-1",
    )
    assert refused.json()["code"] == "mfa_step_up_required"

    changed = client_as(admin).put(
        f"/api/v1/users/{officer.user.id}/membership",
        body,
        format="json",
        HTTP_IDEMPOTENCY_KEY="m-2",
    )
    assert changed.status_code == 200, changed.json()
    assert changed.json()["role"] == "LGA_OFFICER"

    # Same token, next request: the new role and scope are already in force.
    me = officer_client.get("/api/v1/me").json()
    assert me["role"] == "LGA_OFFICER"
    assert me["scope"] == {"type": "LGA", "ids": [str(lga.id)]}
    assert "evidence.view" in me["permissions"]
    assert User.objects.get(id=officer.user.id).scope_version == 2

    event = AuditEvent.objects.get(action="user.membership_changed")
    assert event.diff["before"]["role"] == "WARD_OFFICER"
    assert event.diff["after"]["role"] == "LGA_OFFICER"


def test_the_last_admin_cannot_be_demoted(geography, make_member, client_as):
    admin = make_member()
    ward = Ward.objects.first()
    response = client_as(admin).put(
        f"/api/v1/users/{admin.user.id}/membership",
        {"role": "WARD_OFFICER", "scope_ids": [str(ward.id)]},
        format="json",
        HTTP_IDEMPOTENCY_KEY="m-1",
    )
    assert response.json()["code"] == "last_admin"


def test_device_revocation_ends_its_sessions(make_member, client_as):
    admin = make_member()
    agent = make_member(Role.PU_AGENT, organization=admin.organization)
    device = Device.objects.create(user=agent.user, platform="IOS", app_version="1.0.0")
    session = start_session(
        user=agent.user,
        membership=agent.membership,
        client="MOBILE",
        device=device,
        mfa_at=None,
        ip=None,
    )
    agent_client = client_as(agent)
    agent_client.credentials(HTTP_AUTHORIZATION=f"Bearer {session.access_token}")
    assert agent_client.get("/api/v1/me").status_code == 200

    response = _post(
        client_as(admin), f"/api/v1/users/{agent.user.id}/devices/{device.id}/revoke", "r-1"
    )
    assert response.json()["status"] == "REVOKED"
    assert agent_client.get("/api/v1/me").json()["code"] == "token_revoked"

    unknown = _post(
        client_as(admin),
        f"/api/v1/users/{agent.user.id}/devices/0190a6a0-0000-7000-8000-000000000000/revoke",
        "r-2",
    )
    assert unknown.status_code == 404


def test_idempotency_key_reuse_with_a_different_body(geography, make_member, client_as):
    admin = make_member()
    officer = make_member(Role.WARD_OFFICER, organization=admin.organization)
    ward_ids = list(Ward.objects.values_list("id", flat=True)[:2])
    client = client_as(admin)
    path = f"/api/v1/users/{officer.user.id}/membership"
    first = client.put(
        path,
        {"role": "WARD_OFFICER", "scope_ids": [str(ward_ids[0])]},
        format="json",
        HTTP_IDEMPOTENCY_KEY="k",
    )
    assert first.status_code == 200
    conflict = client.put(
        path,
        {"role": "WARD_OFFICER", "scope_ids": [str(ward_ids[1])]},
        format="json",
        HTTP_IDEMPOTENCY_KEY="k",
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"
