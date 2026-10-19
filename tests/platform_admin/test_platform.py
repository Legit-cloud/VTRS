"""Platform operators: decisions on organizations, master data, messaging, and the limits."""

import io
import uuid

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.accounts.models import Membership
from apps.audit.models import AuditEvent
from apps.core.domain.permissions import Role
from apps.core.rls import system_context
from apps.geography.domain.synthetic import synthetic_master_data
from apps.geography.models import PollingUnit
from apps.geography.services import import_master_data
from apps.organizations.models import Organization, OrganizationStatus

pytestmark = pytest.mark.django_db

KEY = {"HTTP_IDEMPOTENCY_KEY": "k-1"}


@pytest.fixture
def operator(make_member, make_org):
    with system_context():
        platform = Organization.objects.create(
            name="VTRS platform", status=OrganizationStatus.ACTIVE, is_platform=True
        )
    return make_member(Role.PLATFORM_ADMIN, organization=platform, mfa_enabled=True)


def _org(name="Oyo Party", status=OrganizationStatus.PENDING_APPROVAL):
    with system_context():
        return Organization.objects.create(name=name, status=status)


def _post(client, route, org, body=None, key=None):
    return client.post(
        reverse(route, kwargs={"organization_id": org.id}),
        body or {},
        format="json",
        HTTP_IDEMPOTENCY_KEY=key or str(uuid.uuid4()),
    )


def _status(org) -> str:
    with system_context():
        return Organization.objects.get(id=org.id).status


# ---- who can reach it --------------------------------------------------------------------


def test_a_party_admin_cannot_use_the_platform_surface(client_as, make_member):
    client = client_as(make_member(Role.PARTY_ADMIN))
    for route in ("platform-overview", "platform-orgs", "platform-audit", "platform-messaging"):
        assert client.get(reverse(route)).status_code == 403


def test_a_platform_operator_cannot_use_party_data(client_as, operator):
    client = client_as(operator)
    # The list is open to any signed-in user but shows only your own organization's: none.
    assert client.get(reverse("elections")).json()["results"] == []
    assert client.get(reverse("users")).status_code == 403
    assert client.get(reverse("audit-events")).status_code == 403


def test_no_party_admin_can_invite_a_platform_operator(client_as, make_member):
    admin = make_member(Role.PARTY_ADMIN)
    response = client_as(admin).post(
        reverse("invitations"),
        {"role": "PLATFORM_ADMIN", "email": "x@example.org", "full_name": "X"},
        format="json",
        **KEY,
    )
    assert response.status_code in {400, 403}
    with system_context():
        assert not Membership.objects.filter(role="PLATFORM_ADMIN", user__full_name="X").exists()


def test_the_platform_organization_is_not_listed_and_cannot_be_suspended(client_as, operator):
    client = client_as(operator)
    names = [o["name"] for o in client.get(reverse("platform-orgs")).json()["results"]]
    assert "VTRS platform" not in names
    response = _post(client, "platform-org-suspend", operator.organization, {"reason": "x"})
    assert response.status_code == 404


# ---- decisions ---------------------------------------------------------------------------


def test_approve_activates_and_leaves_an_audit_trail(client_as, operator):
    org = _org()
    response = _post(client_as(operator), "platform-org-approve", org)
    assert response.status_code == 200, response.json()
    assert response.json()["status"] == "ACTIVE"
    assert _status(org) == "ACTIVE"
    with system_context():
        event = AuditEvent.objects.get(action="organization.approved", organization_id=org.id)
    assert event.actor_role == "PLATFORM_ADMIN"
    assert event.diff["from"] == "PENDING_APPROVAL"


def test_a_decision_needs_a_fresh_second_factor(client_as, operator):
    org = _org()
    response = _post(client_as(operator, mfa=False), "platform-org-approve", org)
    assert response.status_code == 403
    assert _status(org) == "PENDING_APPROVAL"


def test_reject_and_suspend_need_a_reason_that_is_kept(client_as, operator):
    client = client_as(operator)
    org = _org()
    assert _post(client, "platform-org-reject", org).status_code == 400
    ok = _post(client, "platform-org-reject", org, {"reason": "Registration papers missing"})
    assert ok.status_code == 200
    assert ok.json()["status"] == "REJECTED"
    assert ok.json()["status_reason"] == "Registration papers missing"

    active = _org("Active Party", OrganizationStatus.ACTIVE)
    assert _post(client, "platform-org-suspend", active).status_code == 400
    assert (
        _post(client, "platform-org-suspend", active, {"reason": "Misuse"}).json()["status"]
        == "SUSPENDED"
    )


def test_decisions_only_apply_from_the_right_state(client_as, operator):
    client = client_as(operator)
    active = _org("Already Active", OrganizationStatus.ACTIVE)
    assert _post(client, "platform-org-approve", active).status_code == 400
    pending = _org()
    assert _post(client, "platform-org-reinstate", pending).status_code == 400
    assert _post(client, "platform-org-suspend", pending, {"reason": "x"}).status_code == 400


def test_a_suspended_organization_is_locked_out_at_once_and_can_be_reinstated(
    client_as, operator, make_member
):
    org = _org("Busy Party", OrganizationStatus.ACTIVE)
    admin = make_member(Role.PARTY_ADMIN, organization=org)
    party = client_as(admin)
    assert party.get(reverse("users")).status_code == 200

    _post(client_as(operator), "platform-org-suspend", org, {"reason": "Investigating"})
    assert party.get(reverse("users")).status_code == 401  # the token no longer resolves

    _post(client_as(operator), "platform-org-reinstate", org)
    assert party.get(reverse("users")).status_code == 200


def test_repeating_a_decision_with_the_same_key_changes_nothing_more(client_as, operator):
    client = client_as(operator)
    org = _org()
    first = _post(client, "platform-org-approve", org, key="same")
    second = _post(client, "platform-org-approve", org, key="same")
    assert first.status_code == second.status_code == 200
    assert second["Idempotent-Replayed"] == "true"
    with system_context():
        assert AuditEvent.objects.filter(action="organization.approved").count() == 1


# ---- reads -------------------------------------------------------------------------------


def test_lists_and_overview_cover_every_party(client_as, operator, make_member):
    pending = _org("Pending Party")
    active = _org("Live Party", OrganizationStatus.ACTIVE)
    make_member(Role.PARTY_ADMIN, organization=active)
    client = client_as(operator)

    body = client.get(reverse("platform-orgs")).json()["results"]
    assert {o["name"] for o in body} >= {"Pending Party", "Live Party"}
    live = next(o for o in body if o["name"] == "Live Party")
    assert live["people"] == 1

    queue = client.get(reverse("platform-verification-queue")).json()["results"]
    assert [o["id"] for o in queue] == [str(pending.id)]

    overview = client.get(reverse("platform-overview")).json()
    assert overview["organizations"]["pending_approval"] == 1
    assert overview["organizations"]["active"] == 1
    assert overview["submissions"]["target_per_hour"] == 10_000
    assert any(item["kind"] == "verification" for item in overview["needs_attention"])

    detail = client.get(reverse("platform-org-detail", kwargs={"organization_id": active.id}))
    assert detail.status_code == 200
    admin = detail.json()["admins"][0]
    assert "***" in admin["email"]  # contact details are masked even for operators


def test_unknown_filters_are_refused(client_as, operator):
    response = client_as(operator).get(reverse("platform-orgs"), {"nonsense": "1"})
    assert response.status_code == 400


# ---- master data -------------------------------------------------------------------------


def _csv(**kwargs) -> bytes:
    rows = synthetic_master_data(**kwargs)
    header = list(rows[0])
    out = io.StringIO()
    out.write(",".join(header) + "\n")
    for row in rows:
        out.write(",".join(str(row[h]) for h in header) + "\n")
    return out.getvalue().encode()


def _upload(client, route, content: bytes):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return client.post(
        reverse(route),
        {"file": SimpleUploadedFile("units.csv", content, content_type="text/csv")},
        format="multipart",
    )


def test_a_preview_reports_the_diff_and_writes_nothing(client_as, operator):
    client = client_as(operator)
    content = _csv(lgas=2, wards=4, polling_units=8, seed=3)
    response = _upload(client, "platform-master-data-preview", content)
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["ok"] is True and body["applied"] is False
    assert body["changes"]["polling_units"]["created"] == 8
    assert PollingUnit.objects.count() == 0


def test_an_import_applies_and_a_second_one_changes_nothing(client_as, operator):
    client = client_as(operator)
    content = _csv(lgas=2, wards=4, polling_units=8, seed=3)
    first = _upload(client, "platform-master-data-import", content).json()
    assert first["applied"] is True
    assert PollingUnit.objects.count() == 8
    again = _upload(client, "platform-master-data-preview", content).json()
    assert again["changes"]["polling_units"] == {"created": 0, "updated": 0}


def test_an_import_needs_a_fresh_second_factor_and_a_valid_file(client_as, operator):
    content = _csv(lgas=1, wards=2, polling_units=4, seed=1)
    assert (
        _upload(client_as(operator, mfa=False), "platform-master-data-import", content).status_code
        == 403
    )
    bad = _upload(client_as(operator), "platform-master-data-preview", b"state_code\nOY\n")
    assert bad.status_code == 200
    assert bad.json()["ok"] is False
    assert bad.json()["errors"]


def test_master_data_summary_and_search(client_as, operator):
    import_master_data(synthetic_master_data(lgas=2, wards=4, polling_units=8, seed=3))
    client = client_as(operator)
    state = client.get(reverse("platform-master-data")).json()["states"][0]
    assert state["polling_units"] == 8
    assert state["located_pct"] is not None
    one = PollingUnit.objects.order_by("inec_code").first()
    hit = client.get(reverse("platform-master-data-search"), {"q": one.inec_code}).json()["results"]
    assert hit and hit[0]["code"] == one.inec_code


# ---- messaging ---------------------------------------------------------------------------


def test_messaging_stats_and_a_test_send_to_the_operators_own_address(client_as, operator, inbox):
    client = client_as(operator)
    stats = client.get(reverse("platform-messaging")).json()
    assert {c["channel"] for c in stats["channels"]} == {"SMS", "EMAIL", "WHATSAPP", "IN_APP"}

    sent = client.post(
        reverse("platform-messaging-test"), {"channel": "EMAIL"}, format="json", **KEY
    )
    assert sent.status_code == 200
    assert "***" in sent.json()["sent_to"]
    assert any("test message" in m for m in inbox.messages())


# ---- creating operators ------------------------------------------------------------------


def test_the_command_creates_an_operator_who_enrols_before_doing_anything(api_client):
    call_command(
        "create_platform_admin",
        email="ops@vtrs.example",
        name="Ops One",
        phone="08031234567",
        password="a-long-operator-passphrase",
    )
    login = api_client.post(
        "/api/v1/auth/login",
        {"identifier": "ops@vtrs.example", "password": "a-long-operator-passphrase"},
        format="json",
    )
    assert login.status_code == 200, login.json()
    body = login.json()
    assert body["mfa_enrolment_required"] is True

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {body['access_token']}")
    me = api_client.get("/api/v1/me").json()
    assert me["role"] == "PLATFORM_ADMIN"
    # Without a second factor the platform surface stays shut.
    assert api_client.get(reverse("platform-overview")).status_code == 403


def test_the_command_refuses_a_short_password_and_party_members():
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("create_platform_admin", email="a@b.example", name="A", password="short")


def test_there_can_be_only_one_platform_organization(operator):
    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError), transaction.atomic(), system_context():
        Organization.objects.create(name="Second", is_platform=True)
