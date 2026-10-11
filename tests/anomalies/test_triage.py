"""Working a flag: acknowledge, assign, comment, resolve, reopen (FR-6.9.7, AC-11)."""

import pytest

from apps.aggregation.models import Rollup
from apps.anomalies.models import FlagEvent
from apps.core.domain.permissions import Role
from apps.core.ids import uuid7
from apps.core.rls import system_context
from apps.results.models import PuResult

from .helpers import flags_of, unit_with_coordinates, version_state

pytestmark = pytest.mark.django_db


@pytest.fixture
def flagged(field_):
    """One HIGH flag (far from the unit) at ward A1, plus the people who can work it."""
    f = field_
    pu = unit_with_coordinates(f)
    outcome = f.submit(
        pu,
        gps={
            "lat": round(float(pu.latitude) + 0.5, 6),
            "lng": float(pu.longitude),
            "accuracy_m": 9,
        },
    )
    [flag] = flags_of(outcome["version_id"])
    f.flag = flag
    f.pu = pu
    f.version_id = outcome["version_id"]
    f.ward_officer = f.officer(Role.WARD_OFFICER, f.wards[0])
    f.lga_officer = f.officer(Role.LGA_OFFICER, f.lgas[0])
    return f


def _post(client, flag, action, body=None):
    return client.post(
        f"/api/v1/flags/{flag.id}/{action}",
        body or {},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid7()),
    )


def _open_flags(field):
    with system_context():
        return Rollup.objects.get(
            contest=field.contest, level="STATE", area_id=field.election.state_id
        ).open_flags


def test_the_flag_detail_tells_its_story(flagged):
    f = flagged
    body = f.admin_client().get(f"/api/v1/flags/{f.flag.id}").json()
    assert body["rule_code"] == "GPS_OUT_OF_GEOFENCE"
    assert body["title"] == "Submitted away from the polling unit"
    assert body["status"] == "OPEN"
    assert [e["action"] for e in body["events"]] == ["RAISED"]
    assert body["sla_due_at"] is not None


def test_acknowledging_stops_the_escalation_clock(flagged):
    f = flagged
    client = f.client_as(f.ward_officer)  # a ward officer may acknowledge, not resolve
    response = _post(client, f.flag, "acknowledge")
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["status"] == "ACKNOWLEDGED"
    assert body["sla_due_at"] is None
    assert [e["action"] for e in body["events"]] == ["RAISED", "ACKNOWLEDGED"]
    # Doing it again changes nothing.
    again = _post(client, f.flag, "acknowledge").json()
    assert [e["action"] for e in again["events"]] == ["RAISED", "ACKNOWLEDGED"]


def test_resolving_needs_the_resolve_permission_and_a_note(flagged):
    f = flagged
    ward = f.client_as(f.ward_officer)
    assert (
        _post(ward, f.flag, "resolve", {"outcome": "RESOLVED", "note": "Checked"}).status_code
        == 403
    )
    lga = f.client_as(f.lga_officer)
    assert _post(lga, f.flag, "resolve", {"outcome": "RESOLVED"}).status_code == 400
    assert _post(lga, f.flag, "resolve", {"outcome": "RESOLVED", "note": " "}).status_code == 400
    assert _post(lga, f.flag, "resolve", {"outcome": "MAYBE", "note": "Checked"}).status_code == 400


def test_a_false_positive_returns_the_result_to_normal(flagged):
    f = flagged
    assert version_state(f.version_id) == "REQUIRES_REVIEW"
    assert _open_flags(f) == 1
    response = _post(
        f.client_as(f.lga_officer),
        f.flag,
        "resolve",
        {"outcome": "FALSE_POSITIVE", "note": "Agent phoned in: polling at the ward office"},
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["status"] == "FALSE_POSITIVE"
    assert body["resolution_note"].startswith("Agent phoned in")
    assert version_state(f.version_id) == "SUBMITTED"
    with system_context():
        assert PuResult.objects.get(polling_unit=f.pu).status == "SUBMITTED"
    assert _open_flags(f) == 0  # the rollup follows the flag
    closed_again = _post(
        f.client_as(f.lga_officer), f.flag, "resolve", {"outcome": "RESOLVED", "note": "Again"}
    )
    assert (closed_again.status_code, closed_again.json()["code"]) == (409, "flag_already_closed")


def test_reopening_brings_the_review_back(flagged):
    f = flagged
    lga = f.client_as(f.lga_officer)
    assert _post(lga, f.flag, "reopen", {"note": "Not closed yet"}).status_code == 409
    _post(lga, f.flag, "resolve", {"outcome": "RESOLVED", "note": "Verified by phone"})
    assert version_state(f.version_id) == "SUBMITTED"
    response = _post(lga, f.flag, "reopen", {"note": "Photo does not match the call"})
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "OPEN"
    assert version_state(f.version_id) == "REQUIRES_REVIEW"
    assert _open_flags(f) == 1
    actions = [e["action"] for e in response.json()["events"]]
    assert actions == ["RAISED", "RESOLVED", "REOPENED"]


def test_a_flag_is_only_assigned_to_someone_who_can_see_it(flagged):
    f = flagged
    lga = f.client_as(f.lga_officer)
    ok = _post(lga, f.flag, "assign", {"assignee_id": str(f.ward_officer.user.id)})
    assert ok.status_code == 200, ok.content
    assert ok.json()["assigned_to_id"] == str(f.ward_officer.user.id)

    elsewhere = f.officer(Role.WARD_OFFICER, f.wards[3])
    refused = _post(lga, f.flag, "assign", {"assignee_id": str(elsewhere.user.id)})
    assert (refused.status_code, refused.json()["code"]) == (400, "invalid_assignee")
    agent = f.agents[f.pu.id].member
    assert _post(lga, f.flag, "assign", {"assignee_id": str(agent.user.id)}).status_code == 400

    mine = f.client_as(f.ward_officer).get(
        f"/api/v1/elections/{f.election.id}/flags", {"assigned_to_me": "true"}
    )
    assert len(mine.json()["results"]) == 1
    cleared = _post(lga, f.flag, "assign", {"assignee_id": None})
    assert cleared.json()["assigned_to_id"] is None


def test_comments_are_part_of_the_record(flagged):
    f = flagged
    response = _post(f.client_as(f.ward_officer), f.flag, "comments", {"note": "Calling the agent"})
    assert response.status_code == 200
    assert response.json()["events"][-1]["action"] == "COMMENTED"
    assert _post(f.client_as(f.ward_officer), f.flag, "comments", {"note": "x"}).status_code == 400


def test_scope_applies_to_every_action(flagged):
    f = flagged
    sibling = f.client_as(f.officer(Role.WARD_OFFICER, f.wards[1]))
    other_lga = f.client_as(f.officer(Role.LGA_OFFICER, f.lgas[1]))
    for client in (sibling, other_lga):
        assert client.get(f"/api/v1/flags/{f.flag.id}").status_code == 404
        assert _post(client, f.flag, "acknowledge").status_code == 404
    agent = f.agents[f.pu.id].client
    assert agent.get(f"/api/v1/flags/{f.flag.id}").status_code == 403


def test_the_flag_ledger_cannot_be_edited(flagged, as_superuser):
    from django.db import DatabaseError, connection, transaction

    def refused(sql):
        with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(sql)

    refused("UPDATE anomaly_flag_event SET note = 'edited'")
    refused("DELETE FROM anomaly_flag_event")
    as_superuser()
    refused("UPDATE anomaly_flag_event SET note = 'edited'")
    with system_context():
        assert FlagEvent.objects.count() >= 1


def test_the_summary_counts_and_times_resolution(flagged):
    f = flagged
    url = f"/api/v1/elections/{f.election.id}/flags/summary"
    before = f.admin_client().get(url).json()
    assert before["active_by_severity"] == {"HIGH": 1}
    assert before["active_by_rule"] == {"GPS_OUT_OF_GEOFENCE": 1}
    assert before["closed"] == 0 and before["average_minutes_to_resolve"] is None
    _post(f.client_as(f.lga_officer), f.flag, "resolve", {"outcome": "RESOLVED", "note": "Fine"})
    after = f.admin_client().get(url).json()
    assert after["active_by_severity"] == {}
    assert after["closed"] == 1
    assert after["average_minutes_to_resolve"] is not None
    assert after["by_status"] == {"RESOLVED": 1}


def test_listing_filters_and_strict_parameters(flagged):
    f = flagged
    url = f"/api/v1/elections/{f.election.id}/flags"
    admin = f.admin_client()
    assert len(admin.get(url, {"severity": "HIGH"}).json()["results"]) == 1
    assert admin.get(url, {"severity": "CRITICAL"}).json()["results"] == []
    assert admin.get(url, {"status": "OPEN", "rule_code": "GPS_OUT_OF_GEOFENCE"}).status_code == 200
    assert admin.get(url, {"status": "BOGUS"}).status_code == 400
    assert admin.get(url, {"whatever": "1"}).status_code == 400


def test_a_repeated_request_with_the_same_key_acts_once(flagged):
    f = flagged
    client = f.client_as(f.ward_officer)
    key = str(uuid7())
    url = f"/api/v1/flags/{f.flag.id}/comments"
    first = client.post(url, {"note": "On my way"}, format="json", HTTP_IDEMPOTENCY_KEY=key)
    second = client.post(url, {"note": "On my way"}, format="json", HTTP_IDEMPOTENCY_KEY=key)
    assert (first.status_code, second.status_code) == (200, 200)
    assert second["Idempotent-Replayed"] == "true"
    with system_context():
        assert FlagEvent.objects.filter(flag=f.flag, action="COMMENTED").count() == 1
