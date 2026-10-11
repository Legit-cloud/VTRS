"""Review: approve / reject / resubmit (FR-6.7.4, FR-6.7.5)."""

import pytest
from django.db import DatabaseError, connection, transaction

from apps.aggregation.models import Rollup
from apps.audit.models import AuditEvent
from apps.core.domain.permissions import Perm, Role
from apps.core.ids import uuid7
from apps.core.rls import system_context
from apps.results.models import PuResult, ResultReview, ResultVersion

pytestmark = pytest.mark.django_db


def _review(client, version_id, decision, **body):
    return client.post(
        f"/api/v1/results/{version_id}/review",
        {"decision": decision, **body},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid7()),
    )


def _state_row(field):
    with system_context():
        return Rollup.objects.get(
            contest=field.contest, level="STATE", area_id=field.election.state_id
        )


def _verified_votes(row):
    return {
        v.candidate.party_acronym: v.verified_votes for v in row.votes.select_related("candidate")
    }


def test_approving_a_result_makes_it_verified(reviewed_field):
    pu = reviewed_field.pus[0]
    outcome = reviewed_field.submit(pu, (90, 60))
    state = _state_row(reviewed_field)
    assert (state.reported_pus, state.verified_pus) == (1, 0)

    response = _review(reviewed_field.admin_client(), outcome["version_id"], "APPROVED")
    assert response.status_code == 200, response.content
    assert response.json()["state"] == "APPROVED"

    state = _state_row(reviewed_field)
    assert (state.reported_pus, state.verified_pus) == (1, 1)
    assert _verified_votes(state) == {"AAA": 90, "BBB": 60}
    with system_context():
        assert ResultVersion.objects.get(id=outcome["version_id"]).state == "APPROVED"
        assert PuResult.objects.get(polling_unit=pu).status == "APPROVED"
        review = ResultReview.objects.get()
        assert (review.decision, review.from_state) == ("APPROVED", "SUBMITTED")
        assert AuditEvent.objects.filter(action="result.review_decided").exists()


def test_review_is_off_unless_the_election_enables_it(field_):
    outcome = field_.submit(field_.pus[0])
    response = _review(field_.admin_client(), outcome["version_id"], "APPROVED")
    assert (response.status_code, response.json()["code"]) == (409, "review_not_enabled")


def test_rejecting_needs_a_reason(reviewed_field):
    outcome = reviewed_field.submit(reviewed_field.pus[0])
    client = reviewed_field.admin_client()
    assert _review(client, outcome["version_id"], "REJECTED").status_code == 400
    assert _review(client, outcome["version_id"], "REJECTED", reason="  ").status_code == 400
    with system_context():
        assert ResultReview.objects.count() == 0


def test_rejection_keeps_the_record_and_the_head_falls_back(reviewed_field):
    pu = reviewed_field.pus[0]
    first = reviewed_field.submit(pu, (100, 50))
    second = reviewed_field.submit(pu, (300, 50), parent_version_id=first["version_id"])
    response = _review(
        reviewed_field.admin_client(),
        second["version_id"],
        "REJECTED",
        reason="Sheet total does not match the photo",
    )
    assert response.status_code == 200, response.content
    assert response.json()["head_version_id"] == first["version_id"]

    with system_context():
        rejected = ResultVersion.objects.get(id=second["version_id"])
        assert rejected.state == "REJECTED"
        assert rejected.valid == 350  # the original numbers are untouched
        assert ResultReview.objects.get().reason == "Sheet total does not match the photo"
    assert _verified_votes(_state_row(reviewed_field)) == {"AAA": 0, "BBB": 0}
    votes = {
        v.candidate.party_acronym: v.reported_votes
        for v in _state_row(reviewed_field).votes.select_related("candidate")
    }
    assert votes == {"AAA": 100, "BBB": 50}  # back to the earlier version


def test_rejecting_the_only_version_leaves_no_result(reviewed_field):
    pu = reviewed_field.pus[0]
    outcome = reviewed_field.submit(pu)
    _review(reviewed_field.admin_client(), outcome["version_id"], "REJECTED", reason="Wrong unit")
    with system_context():
        result = PuResult.objects.get(polling_unit=pu)
        assert (result.status, result.head_version_id) == ("NO_RESULT", None)
    assert _state_row(reviewed_field).reported_pus == 0


def test_the_agent_sees_why_and_can_resubmit_without_a_fork_flag(reviewed_field):
    pu = reviewed_field.pus[0]
    outcome = reviewed_field.submit(pu, (100, 50))
    _review(
        reviewed_field.admin_client(),
        outcome["version_id"],
        "REJECTED",
        reason="Photo is of another unit",
    )
    agent = reviewed_field.agents[pu.id].client
    status = agent.get("/api/v1/sync/status", {"ids": outcome["version_id"]}).json()[0]
    assert status["state"] == "REJECTED"
    assert status["review"]["reason"] == "Photo is of another unit"
    assert status["review"]["decision"] == "REJECTED"

    resubmitted = reviewed_field.submit(pu, (101, 50), parent_version_id=outcome["version_id"])
    assert resubmitted["version_no"] == 2
    assert resubmitted["is_head"] is True
    assert resubmitted["flags"] == []  # a resubmission is not a fork


def test_flags_must_be_acknowledged_to_approve(reviewed_field):
    pu = reviewed_field.pus[0]
    flagged = reviewed_field.submit(
        pu, (100, 50), totals={"accredited": 400, "valid": 140, "rejected": 5, "total_cast": 145}
    )
    assert flagged["status"] == "REQUIRES_REVIEW"
    client = reviewed_field.admin_client()

    blocked = _review(client, flagged["version_id"], "APPROVED")
    assert (blocked.status_code, blocked.json()["code"]) == (409, "flags_unacknowledged")
    assert blocked.json()["errors"]["flags"] == ["ARITHMETIC_VARIANCE"]

    done = _review(client, flagged["version_id"], "APPROVED", acknowledge_flags=True)
    assert done.status_code == 200
    with system_context():
        assert ResultReview.objects.get().acknowledged_flags == ["ARITHMETIC_VARIANCE"]


def test_only_the_counting_version_can_be_reviewed(reviewed_field):
    pu = reviewed_field.pus[0]
    first = reviewed_field.submit(pu, (100, 50))
    reviewed_field.submit(pu, (110, 50), parent_version_id=first["version_id"])
    response = _review(reviewed_field.admin_client(), first["version_id"], "APPROVED")
    assert (response.status_code, response.json()["code"]) == (409, "not_head_version")


def test_a_decision_cannot_be_repeated(reviewed_field):
    outcome = reviewed_field.submit(reviewed_field.pus[0])
    client = reviewed_field.admin_client()
    assert _review(client, outcome["version_id"], "APPROVED").status_code == 200
    again = _review(client, outcome["version_id"], "APPROVED")
    assert (again.status_code, again.json()["code"]) == (409, "already_decided")


def test_an_approved_result_can_still_be_rejected(reviewed_field):
    outcome = reviewed_field.submit(reviewed_field.pus[0])
    client = reviewed_field.admin_client()
    _review(client, outcome["version_id"], "APPROVED")
    response = _review(client, outcome["version_id"], "REJECTED", reason="Found a recount sheet")
    assert response.status_code == 200
    assert _state_row(reviewed_field).verified_pus == 0


def test_the_same_idempotency_key_replays_the_decision(reviewed_field):
    outcome = reviewed_field.submit(reviewed_field.pus[0])
    client = reviewed_field.admin_client()
    key = str(uuid7())
    url = f"/api/v1/results/{outcome['version_id']}/review"
    first = client.post(url, {"decision": "APPROVED"}, format="json", HTTP_IDEMPOTENCY_KEY=key)
    second = client.post(url, {"decision": "APPROVED"}, format="json", HTTP_IDEMPOTENCY_KEY=key)
    assert (first.status_code, second.status_code) == (200, 200)
    assert second["Idempotent-Replayed"] == "true"
    with system_context():
        assert ResultReview.objects.count() == 1


def test_who_may_review_and_where(reviewed_field):
    f = reviewed_field
    ward_a1, ward_a2 = f.wards[0], f.wards[1]
    outcome = f.submit(f.pus_of(ward_a1)[0])

    own_ward = f.officer_client(Role.WARD_OFFICER, ward_a1)
    sibling_ward = f.officer_client(Role.WARD_OFFICER, ward_a2)
    lga_officer = f.officer_client(Role.LGA_OFFICER, f.lgas[0])
    agent = f.agents[f.pus_of(ward_a1)[0].id].client

    assert _review(agent, outcome["version_id"], "APPROVED").status_code == 403
    assert _review(lga_officer, outcome["version_id"], "APPROVED").status_code == 403
    assert _review(sibling_ward, outcome["version_id"], "APPROVED").status_code == 404
    assert _review(own_ward, outcome["version_id"], "APPROVED").status_code == 200


def test_an_lga_officer_with_the_grant_can_review_inside_the_lga(reviewed_field):
    f = reviewed_field
    outcome = f.submit(f.pus_of(f.wards[0])[0])
    member = f.make_member(
        Role.LGA_OFFICER,
        scope_ids=[f.lgas[0].id],
        organization=f.org,
        granted=[Perm.RESULTS_REVIEW],
    )
    assert _review(f.client_as(member), outcome["version_id"], "APPROVED").status_code == 200


def test_the_review_queue_lists_what_is_waiting_in_scope(reviewed_field):
    f = reviewed_field
    ward_a1, ward_b1 = f.wards[0], f.wards[2]
    mine = f.submit(f.pus_of(ward_a1)[0], (10, 5))
    f.submit(f.pus_of(ward_b1)[0], (1, 1))
    url = f"/api/v1/elections/{f.election.id}/review-queue"

    admin_rows = f.admin_client().get(url).json()["results"]
    assert len(admin_rows) == 2

    ward_client = f.officer_client(Role.WARD_OFFICER, ward_a1)
    rows = ward_client.get(url).json()["results"]
    assert [r["version_id"] for r in rows] == [mine["version_id"]]
    assert rows[0]["votes"][0]["party_acronym"] == "AAA"
    assert rows[0]["polling_unit_code"].startswith("SYN-01-01")

    _review(ward_client, mine["version_id"], "APPROVED")
    assert ward_client.get(url).json()["results"] == []


def test_the_review_ledger_cannot_be_edited(reviewed_field, as_superuser):
    outcome = reviewed_field.submit(reviewed_field.pus[0])
    _review(reviewed_field.admin_client(), outcome["version_id"], "REJECTED", reason="Duplicate")

    def refused(sql):
        with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(sql)

    refused("UPDATE result_review SET reason = 'edited'")
    refused("DELETE FROM result_review")
    as_superuser()
    refused("UPDATE result_review SET reason = 'edited'")
