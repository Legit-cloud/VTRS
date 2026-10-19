"""Reconciliation: freeze the rollups of a closed election (spec section 11, DD-05)."""

from datetime import timedelta

import pytest
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from apps.accounts.services.sessions import start_session
from apps.aggregation.models import ReconciliationSnapshot, Rollup
from apps.audit.models import AuditEvent
from apps.core.domain.canonical import payload_hash
from apps.core.ids import uuid7
from apps.core.rls import system_context
from apps.elections.models import Election

pytestmark = pytest.mark.django_db


def _close(field):
    response = field.admin_client().post(
        f"/api/v1/elections/{field.election.id}/transition", {"to": "CLOSED"}, format="json"
    )
    assert response.status_code == 200, response.content


def _reconcile(client, field):
    return client.post(f"/api/v1/elections/{field.election.id}/reconcile")


def _decide(field, outcome, decision="APPROVED", **body):
    if decision == "APPROVED":
        field.attach_sheet(outcome)
    return field.admin_client().post(
        f"/api/v1/results/{outcome['version_id']}/review",
        {"decision": decision, **body},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid7()),
    )


def test_a_live_election_cannot_be_reconciled(field_):
    response = _reconcile(field_.admin_client(), field_)
    assert (response.status_code, response.json()["code"]) == (409, "invalid_transition")


def test_the_transition_endpoint_does_not_offer_reconciled(field_):
    _close(field_)
    response = field_.admin_client().post(
        f"/api/v1/elections/{field_.election.id}/transition", {"to": "RECONCILED"}, format="json"
    )
    assert response.status_code == 400


def test_reconciling_needs_a_fresh_second_factor(field_):
    _close(field_)
    stale = start_session(
        user=field_.admin.user,
        membership=field_.admin.membership,
        client="WEB",
        mfa_at=timezone.now() - timedelta(hours=1),
        ip=None,
    )
    client = field_.client_as(field_.admin)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {stale.access_token}")
    assert _reconcile(client, field_).json()["code"] == "mfa_step_up_required"


def test_readiness_reports_what_is_missing(reviewed_field):
    f = reviewed_field
    pending = f.submit(f.pus[0])
    f.submit(f.pus[1])
    _close(f)
    url = f"/api/v1/elections/{f.election.id}/reconciliation"
    body = f.admin_client().get(url).json()
    assert body["unverified_results"] == 2
    assert body["can_reconcile"] is True
    assert body["rollup_differences"] == []
    _decide(f, pending)
    assert f.admin_client().get(url).json()["unverified_results"] == 1


def test_unverified_results_do_not_block_reconciliation(reviewed_field):
    """The snapshot keeps the reported and the verified figures side by side."""
    f = reviewed_field
    f.submit(f.pus[0])
    _close(f)
    response = _reconcile(f.admin_client(), f)
    assert response.status_code == 200, response.content
    assert (response.json()["reported_pus"], response.json()["verified_pus"]) == (1, 0)


def test_reconciling_freezes_results_and_stores_a_snapshot(reviewed_field):
    f = reviewed_field
    first = f.submit(f.pus[0], (90, 60))
    second = f.submit(f.pus[1], (100, 120))
    for outcome in (first, second):
        decided = _decide(f, outcome)
        assert decided.status_code == 200, decided.content
    _close(f)

    response = _reconcile(f.admin_client(), f)
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["status"] == "RECONCILED"
    assert (body["reported_pus"], body["verified_pus"]) == (2, 2)

    with system_context():
        election = Election.objects.get(id=f.election.id)
        snapshot = ReconciliationSnapshot.objects.get()
        assert election.status == "RECONCILED"
        assert snapshot.config_hash == election.config_hash
        assert snapshot.sha256 == payload_hash(snapshot.data)
        assert body["snapshot_sha256"] == snapshot.sha256
        state = [r for r in snapshot.data["rows"] if r["level"] == "STATE"]
        assert len(state) == 1
        assert state[0]["verified_valid"] == 370
        assert AuditEvent.objects.filter(action="election.reconciled").exists()

    # Nothing can change any more.
    late = f.agents[f.pus[2].id].client.post("/api/v1/submissions", f.item(f.pus[2]), format="json")
    assert late.json()["code"] == "capture_not_open"
    reject = _decide(f, first, "REJECTED", reason="Too late")
    assert (reject.status_code, reject.json()["code"]) == (409, "results_frozen")
    again = _reconcile(f.admin_client(), f)
    assert again.status_code == 409


def test_the_snapshot_is_append_only(field_, as_superuser):
    field_.submit(field_.pus[0])
    _close(field_)
    assert _reconcile(field_.admin_client(), field_).status_code == 200

    def refused(sql):
        with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(sql)

    refused("UPDATE reconciliation_snapshot SET sha256 = repeat('0', 64)")
    refused("DELETE FROM reconciliation_snapshot")
    as_superuser()
    refused("UPDATE reconciliation_snapshot SET sha256 = repeat('0', 64)")


def test_reconciling_repairs_drift_before_freezing_it(field_):
    f = field_
    f.submit(f.pus[0], (60, 40))
    with system_context():
        Rollup.objects.filter(contest=f.contest, level="STATE").update(reported_valid=1)
    _close(f)
    assert _reconcile(f.admin_client(), f).status_code == 200
    with system_context():
        snapshot = ReconciliationSnapshot.objects.get()
        state = next(r for r in snapshot.data["rows"] if r["level"] == "STATE")
        assert state["reported_valid"] == 100
