"""Audit access, health, analytics, data quality and the alert policy (spec sections 12, 13)."""

import json
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.accounts.services.sessions import start_session
from apps.anomalies.models import AlertPolicy
from apps.core.domain.permissions import Role
from apps.core.ids import uuid7
from apps.core.rls import system_context
from apps.evidence.models import EvidenceFile
from apps.geography.models import PollingUnit

from ..anomalies.helpers import (
    flags_of,
    notifications_for,
    unit_with_coordinates,
)

pytestmark = pytest.mark.django_db


def _stale_client(f):
    session = start_session(
        user=f.admin.user,
        membership=f.admin.membership,
        client="WEB",
        mfa_at=timezone.now() - timedelta(hours=2),
        ip=None,
    )
    client = f.client_as(f.admin)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {session.access_token}")
    return client


# --- Audit trail ----------------------------------------------------------------------------


def test_the_audit_trail_is_for_admins_and_stays_in_the_organization(
    field_, make_org, make_member, client_as
):
    f = field_
    f.submit(f.pus[0])
    events = f.admin_client().get("/api/v1/audit/events").json()["results"]
    actions = {e["action"] for e in events}
    assert "result.version_accepted" in actions

    only_results = f.admin_client().get("/api/v1/audit/events", {"action": "result."}).json()
    assert only_results["results"] and all(
        e["action"].startswith("result.") for e in only_results["results"]
    )

    other_org = make_org("Another Party")
    stranger = client_as(make_member(Role.PARTY_ADMIN, organization=other_org, mfa_enabled=True))
    assert stranger.get("/api/v1/audit/events", {"action": "result."}).json()["results"] == []

    ward = f.client_as(f.officer(Role.WARD_OFFICER, f.wards[0]))
    assert ward.get("/api/v1/audit/events").status_code == 403


def test_the_audit_window_is_bounded(field_):
    f = field_
    now = timezone.now()
    admin = f.admin_client()
    url = "/api/v1/audit/events"
    assert admin.get(url, {"since": (now - timedelta(days=40)).isoformat()}).status_code == 400
    assert admin.get(url, {"since": "yesterday"}).status_code == 400
    assert (
        admin.get(
            url, {"since": now.isoformat(), "until": (now - timedelta(hours=1)).isoformat()}
        ).status_code
        == 400
    )
    assert admin.get(url, {"nope": "1"}).status_code == 400


# --- Health -----------------------------------------------------------------------------------


def test_health_reports_components_and_this_organizations_backlog(field_):
    f = field_
    body = f.admin_client().get("/api/v1/admin/health").json()
    assert body["status"] in {"ok", "degraded"}
    assert {
        "database",
        "cache",
        "broker",
        "storage",
        "outbox",
        "audit_sealing",
        "evidence",
        "notifications",
        "exports",
        "flags",
    } <= set(body["components"])
    assert body["components"]["database"]["status"] == "ok"

    pu = f.pus[0]
    outcome = f.submit(pu)
    with system_context():
        EvidenceFile.objects.create(
            id=uuid7(),
            organization=f.org,
            result_version_id=outcome["version_id"],
            polling_unit=pu,
            ward_id=pu.ward_id,
            lga_id=pu.lga_id,
            uploaded_by=f.agents[pu.id].member.user,
            kind="EC8A",
            object_key=f"org/x/{uuid7()}.jpg",
            size=10,
            mime="image/jpeg",
            sha256_client="0" * 64,
            status="PENDING_UPLOAD",
        )
        EvidenceFile.objects.update(created_at=timezone.now() - timedelta(minutes=30))
    degraded = f.admin_client().get("/api/v1/admin/health").json()
    assert degraded["components"]["evidence"]["uploads_waiting_over_10_min"] == 1
    assert degraded["components"]["evidence"]["status"] == "degraded"
    assert degraded["status"] == "degraded"


def test_health_is_admin_only(field_):
    f = field_
    ward = f.client_as(f.officer(Role.WARD_OFFICER, f.wards[0]))
    assert ward.get("/api/v1/admin/health").status_code == 403
    assert ward.get("/api/v1/admin/data-quality").status_code == 403


# --- Analytics --------------------------------------------------------------------------------


def test_programme_analytics(field_):
    f = field_
    now = timezone.now()
    on_time = f.submit(f.pus[0])
    late = f.submit(f.pus[1], device_captured_at=(now - timedelta(minutes=45)).isoformat())
    f.submit(f.pus[2], parent_version_id=None)
    assert on_time and late
    body = f.admin_client().get(f"/api/v1/elections/{f.election.id}/analytics").json()
    assert body["assignment"] == {
        "expected_polling_units": 8,
        "assigned_polling_units": 8,
        "completion_pct": 100.0,
    }
    assert body["capture"]["polling_units_reported"] == 3
    assert body["capture"]["submission_completion_pct"] == 37.5
    # Three results, none with its sheet yet, so none complete.
    assert body["submission"]["submissions"] == 3
    assert body["submission"]["complete"] == 0
    assert body["submission"]["complete_pct"] == 0.0
    # Two arrived at once and one 45 minutes after capture: the median is the quick ones.
    assert body["submission"]["median_receipt_delay_seconds"] < 60
    assert body["submission"]["p90_receipt_delay_seconds"] is None
    assert body["invitations"]["sent"] == 0
    assert body["integrity"]["flags_raised"] >= 0


def test_analytics_follow_the_callers_scope(field_):
    f = field_
    f.submit(f.pus_of(f.wards[0])[0])
    f.submit(f.pus_of(f.wards[2])[0])
    ward = f.client_as(f.officer(Role.WARD_OFFICER, f.wards[0]))
    body = ward.get(f"/api/v1/elections/{f.election.id}/analytics").json()
    assert body["capture"]["polling_units_reported"] == 1
    assert body["assignment"]["expected_polling_units"] == 2
    assert "invitations" not in body  # organization-wide, so not for a ward officer


# --- Data quality -----------------------------------------------------------------------------


def test_data_quality_counts_gaps(field_):
    f = field_
    with system_context():
        PollingUnit.objects.filter(id=f.pus[0].id).update(latitude=None, longitude=None)
        PollingUnit.objects.filter(id=f.pus[1].id).update(registered_voters=None)
    body = f.admin_client().get("/api/v1/admin/data-quality").json()
    assert body["polling_units"] == 8
    assert body["without_coordinates"] >= 1
    assert body["without_registered_voters"] == 1
    assert body["worst_lgas_for_coordinates"][0]["missing"] >= 1


# --- Alert policy -----------------------------------------------------------------------------


def _put(client, matrix):
    return client.put("/api/v1/admin/alert-policy", {"matrix": matrix}, format="json")


def test_an_organization_can_retune_who_is_woken_up(field_):
    f = field_
    ward_officer = f.officer(Role.WARD_OFFICER, f.wards[0])
    lga_officer = f.officer(Role.LGA_OFFICER, f.lgas[0])
    pu = unit_with_coordinates(f)
    admin = f.admin_client()

    default = admin.get("/api/v1/admin/alert-policy").json()
    assert default["overridden"] is False
    assert default["effective"]["MEDIUM"]["notify"] == ["WARD"]

    response = _put(admin, {"MEDIUM": {"notify": ["WARD", "LGA"], "ack_minutes": 20}})
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["overridden"] is True
    assert body["effective"]["MEDIUM"]["notify"] == ["WARD", "LGA"]
    assert body["effective"]["MEDIUM"]["ack_minutes"] == 20
    assert body["effective"]["HIGH"] == default["effective"]["HIGH"]  # untouched

    far_future = (timezone.now() + timedelta(hours=6)).isoformat()
    outcome = f.submit(pu, device_captured_at=far_future)
    [flag] = [x for x in flags_of(outcome["version_id"]) if x.rule_code == "DEVICE_CLOCK_AHEAD"]
    assert flag.escalation_level == 1
    assert (flag.sla_due_at - timezone.now()) < timedelta(minutes=21)
    assert [n.kind for n in notifications_for(lga_officer.user.id)] == ["ANOMALY"]
    assert [n.kind for n in notifications_for(ward_officer.user.id)] == ["ANOMALY"]

    reset = admin.delete("/api/v1/admin/alert-policy").json()
    assert reset["overridden"] is False
    assert reset["effective"]["MEDIUM"]["notify"] == ["WARD"]
    with system_context():
        assert AlertPolicy.objects.count() == 0


@pytest.mark.parametrize(
    "matrix",
    [
        {"URGENT": {"notify": ["WARD"]}},
        {"HIGH": {"notify": ["CHIEF"]}},
        {"HIGH": {"channels": ["CARRIER_PIGEON"]}},
        {"HIGH": {"ack_minutes": 0}},
        {"HIGH": {"ack_minutes": 99999}},
        {"HIGH": {"colour": "red"}},
        {"CRITICAL": {"notify": []}},
    ],
)
def test_nonsense_policies_are_refused(field_, matrix):
    response = _put(field_.admin_client(), matrix)
    assert response.status_code == 400, response.content


def test_policy_changes_need_the_admin_and_a_fresh_second_factor(field_):
    f = field_
    ward = f.client_as(f.officer(Role.WARD_OFFICER, f.wards[0]))
    assert _put(ward, {"HIGH": {"ack_minutes": 5}}).status_code == 403
    assert ward.get("/api/v1/admin/alert-policy").status_code == 403
    stale = _put(_stale_client(f), {"HIGH": {"ack_minutes": 5}})
    assert stale.json()["code"] == "mfa_step_up_required"
    with system_context():
        assert AlertPolicy.objects.count() == 0


def test_policy_changes_are_audited_with_before_and_after(field_):
    from apps.audit.models import AuditEvent

    f = field_
    admin = f.admin_client()
    _put(admin, {"HIGH": {"ack_minutes": 10}})
    _put(admin, {"HIGH": {"ack_minutes": 12}})
    events = list(AuditEvent.objects.filter(action="alert_policy.updated").order_by("at"))
    assert [e.diff["after"]["HIGH"]["ack_minutes"] for e in events] == [10, 12]
    assert events[1].diff["before"]["HIGH"]["ack_minutes"] == 10


# --- Retention --------------------------------------------------------------------------------


def test_the_retention_report_lists_but_never_deletes(field_):
    f = field_
    f.submit(f.pus[0])
    admin = f.admin_client()
    admin.post(f"/api/v1/elections/{f.election.id}/transition", {"to": "CLOSED"}, format="json")
    assert admin.post(f"/api/v1/elections/{f.election.id}/reconcile").status_code == 200

    out = StringIO()
    call_command("retention_report", "--json", stdout=out)
    report = json.loads(out.getvalue())
    assert report["retention_years"]["evidence"] == 7
    [row] = report["elections"]
    assert row["election_id"] == str(f.election.id)
    assert row["evidence_past_retention"] is False
    assert row["result_versions"] == 1
    with system_context():
        assert EvidenceFile.objects.count() == 0  # it had none, and nothing was touched
