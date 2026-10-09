"""AC-05 - AC-08 (server side): offline submissions sync, are never duplicated, never lost,
and never silently dropped for being wrong."""

import pytest
from django.db import DatabaseError, connection, transaction

from apps.anomalies.models import AnomalyFlag
from apps.audit.models import AuditEvent
from apps.core.ids import uuid7
from apps.core.models import OutboxEvent
from apps.core.rls import system_context
from apps.elections.models import Election
from apps.results.domain.versions import VersionState, select_head
from apps.results.models import PuResult, ResultVersion, VoteLine

from .conftest import seal

pytestmark = pytest.mark.django_db


def _flags(version_id):
    with system_context():
        return sorted(
            AnomalyFlag.objects.filter(result_version_id=version_id).values_list(
                "rule_code", flat=True
            )
        )


def _version(version_id):
    with system_context():
        return ResultVersion.objects.select_related("pu_result").get(id=version_id)


def test_accepted_submission(scenario):
    item = scenario.item()
    [outcome] = scenario.submit(item)
    assert outcome["status"] == "SYNCED", outcome
    assert (outcome["version_no"], outcome["is_head"], outcome["replayed"]) == (1, True, False)
    assert outcome["flags"] == []

    version = _version(item["version_id"])
    assert (version.valid, version.rejected, version.total_cast, version.accredited) == (
        200,
        5,
        205,
        210,
    )
    assert version.server_received_at is not None
    assert version.device_id == scenario.agent.device.id
    assert str(version.gps_lat) == "7.391200"
    with system_context():
        lines = dict(
            VoteLine.objects.filter(result_version=version).values_list(
                "candidate__party_acronym", "votes"
            )
        )
        pu_result = PuResult.objects.get(contest=scenario.contest, polling_unit=scenario.pu)
    assert lines == {"AAA": 120, "BBB": 80}
    assert (pu_result.head_version_id, pu_result.status, pu_result.version_count) == (
        version.id,
        "SUBMITTED",
        1,
    )
    assert AuditEvent.objects.filter(
        action="result.version_accepted", object_id=str(version.id)
    ).exists()
    assert OutboxEvent.objects.filter(topic="result.version_accepted").count() == 1


def test_retries_never_duplicate(scenario):
    """AC-08: the same version id again returns the stored outcome; nothing new is written."""
    item = scenario.item()
    first = scenario.submit(item)[0]
    again = scenario.submit(item, item)  # a flaky network can even repeat it within a batch
    assert [o["replayed"] for o in again] == [True, True]
    assert all(o["status"] == "SYNCED" and o["version_no"] == first["version_no"] for o in again)
    with system_context():
        assert ResultVersion.objects.filter(id=item["version_id"]).count() == 1
        assert PuResult.objects.get().version_count == 1


def test_same_version_id_with_different_content_is_refused(scenario):
    item = scenario.item()
    scenario.submit(item)
    tampered = seal({**item, "votes": [{**item["votes"][0], "votes": 999}, item["votes"][1]]})
    [outcome] = scenario.submit(tampered)
    assert (outcome["status"], outcome["http_status"], outcome["code"]) == (
        "FAILED",
        409,
        "idempotency_conflict",
    )
    assert AuditEvent.objects.filter(action="result.idempotency_conflict").exists()


def test_payload_hash_must_match(scenario):
    item = {**scenario.item(), "payload_hash": "0" * 64}
    [outcome] = scenario.submit(item)
    assert outcome["code"] == "payload_hash_mismatch"


def test_one_bad_item_does_not_sink_the_batch(scenario):
    good = scenario.item()
    bad = {"version_id": str(uuid7()), "contest_id": "nope"}
    outcomes = scenario.submit(bad, good)
    assert outcomes[0]["status"] == "FAILED" and outcomes[0]["code"] == "malformed"
    assert "contest_id" in outcomes[0]["errors"]
    assert outcomes[1]["status"] == "SYNCED"


def test_list_limits_inside_an_item_are_enforced(scenario):
    item = scenario.item()
    too_many_lines = seal({**item, "votes": item["votes"] * 51})  # 102 lines
    too_many_photos = seal({**scenario.item(), "evidence": [{}] * 6})
    outcomes = scenario.submit(too_many_lines, too_many_photos)
    assert outcomes[0]["code"] == "malformed" and "votes" in outcomes[0]["errors"]
    assert outcomes[1]["code"] == "malformed" and "evidence" in outcomes[1]["errors"]


def test_batches_are_limited_to_ten(scenario):
    response = scenario.agent.client.post(
        "/api/v1/sync/submissions", {"items": [scenario.item() for _ in range(11)]}, format="json"
    )
    assert response.status_code == 400


@pytest.mark.parametrize(
    ("change", "rule"),
    [
        (
            {
                "votes": [120, 80],
                "totals": {"accredited": 210, "valid": 190, "rejected": 5, "total_cast": 195},
            },
            "ARITHMETIC_VARIANCE",
        ),
        (
            {
                "votes": [120, 80],
                "totals": {"accredited": 210, "valid": 200, "rejected": 5, "total_cast": 300},
            },
            "ARITHMETIC_VARIANCE",
        ),
        (
            {
                "votes": [120, 80],
                "totals": {"accredited": 150, "valid": 200, "rejected": 5, "total_cast": 205},
            },
            "OVER_VOTING",
        ),
        (
            {
                "votes": [600, 500],
                "totals": {"accredited": 1200, "valid": 1100, "rejected": 0, "total_cast": 1100},
            },
            "OVER_VOTING",
        ),
    ],
)
def test_wrong_results_are_accepted_and_flagged(scenario, change, rule):
    """Never silently dropped for being wrong: stored, flagged, routed to review."""
    item = scenario.item(**change)
    [outcome] = scenario.submit(item)
    assert outcome["status"] == "REQUIRES_REVIEW", outcome
    assert rule in outcome["flags"]
    assert _version(item["version_id"]).state == VersionState.REQUIRES_REVIEW
    assert rule in _flags(item["version_id"])


def test_ballot_and_sheet_shape(scenario):
    missing_candidate = scenario.item()
    missing_candidate = seal({**missing_candidate, "votes": missing_candidate["votes"][:1]})
    extra_total = scenario.item()
    extra_total = seal(
        {
            **extra_total,
            "totals": {k: v for k, v in extra_total["totals"].items() if k != "rejected"},
        }
    )
    outcomes = scenario.submit(missing_candidate, extra_total)
    assert outcomes[0]["code"] == "candidate_mismatch"
    assert outcomes[1]["code"] == "sheet_fields_mismatch"


def test_unassigned_polling_unit_is_refused_and_flagged(scenario):
    [outcome] = scenario.submit(scenario.item(pu=scenario.other_pu))
    assert (outcome["http_status"], outcome["code"]) == (403, "unassigned_polling_unit")
    with system_context():
        flag = AnomalyFlag.objects.get(rule_code="UNASSIGNED_PU_ATTEMPT")
        assert (flag.severity, flag.polling_unit_id, flag.result_version_id) == (
            "CRITICAL",
            scenario.other_pu.id,
            None,
        )
        assert not ResultVersion.objects.exists()
    assert AuditEvent.objects.filter(action="result.unassigned_attempt").exists()


def test_capture_window(scenario):
    with system_context():
        Election.objects.filter(id=scenario.election.id).update(status="LOCKED")
    [early] = scenario.submit(scenario.item())
    assert early["code"] == "capture_not_open"

    with system_context():
        Election.objects.filter(id=scenario.election.id).update(status="CLOSED")
    late = scenario.item()
    [outcome] = scenario.submit(late)
    # Captured offline, synced after close: kept, but a human must accept it.
    assert outcome["status"] == "REQUIRES_REVIEW"
    assert outcome["flags"] == ["LATE_SUBMISSION"]


def test_device_must_match_the_session(scenario):
    item = scenario.item(device_id=str(uuid7()))
    [outcome] = scenario.submit(item)
    assert (outcome["http_status"], outcome["code"]) == (403, "device_mismatch")


def test_config_version_mismatch_is_flagged(scenario):
    [outcome] = scenario.submit(scenario.item(config_version=4))
    assert outcome["flags"] == ["CONFIG_VERSION_MISMATCH"]


def test_corrections_are_new_versions(scenario):
    first = scenario.item()
    scenario.submit(first)
    correction = scenario.item(parent_version_id=first["version_id"], votes=[121, 80])
    [outcome] = scenario.submit(correction)
    assert (outcome["status"], outcome["version_no"], outcome["is_head"]) == ("SYNCED", 2, True)
    assert _version(first["version_id"]).valid == 200  # the original is never edited
    with system_context():
        assert PuResult.objects.get().head_version_id == _version(correction["version_id"]).id


def test_forks_and_second_sources_are_flagged(scenario):
    first = scenario.item()
    scenario.submit(first)
    fork = scenario.item(parent_version_id=None)
    assert scenario.submit(fork)[0]["flags"] == ["VERSION_FORK"]

    second_agent = scenario.make_agent()
    other = scenario.item(agent=second_agent, parent_version_id=fork["version_id"])
    [outcome] = scenario.submit(other, agent=second_agent)
    assert outcome["flags"] == ["DUPLICATE_SOURCE"]
    with system_context():
        assert PuResult.objects.count() == 1
        assert ResultVersion.objects.count() == 3


def test_versions_and_vote_lines_are_immutable(scenario, as_superuser):
    item = scenario.item()
    scenario.submit(item)

    def refused(sql):
        with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(sql, [item["version_id"]])

    refused("UPDATE result_version SET valid = 999 WHERE id = %s")
    refused("DELETE FROM result_version WHERE id = %s")
    refused("UPDATE vote_line SET votes = 999 WHERE result_version_id = %s")
    refused("DELETE FROM vote_line WHERE result_version_id = %s")
    # A review decision may move the state, and nothing else.
    with system_context(), connection.cursor() as cursor:
        cursor.execute(
            "UPDATE result_version SET state = 'APPROVED' WHERE id = %s", [item["version_id"]]
        )
    # Even the database owner cannot alter the data (the trigger, not just the grants).
    as_superuser()
    refused("UPDATE result_version SET valid = 999 WHERE id = %s")


def test_sync_status(scenario):
    mine = scenario.item()
    scenario.submit(mine)
    other_agent = scenario.make_agent()
    theirs = scenario.item(agent=other_agent)
    scenario.submit(theirs, agent=other_agent)
    unknown = str(uuid7())
    response = scenario.agent.client.get(
        "/api/v1/sync/status",
        {"ids": ",".join([mine["version_id"], theirs["version_id"], unknown])},
    )
    rows = {r["version_id"]: r for r in response.json()}
    assert rows[mine["version_id"]]["status"] == "SYNCED"
    assert rows[mine["version_id"]]["version_no"] == 1
    assert rows[theirs["version_id"]]["status"] == "UNKNOWN"  # not yours: indistinguishable
    assert rows[unknown]["status"] == "UNKNOWN"
    assert scenario.agent.client.get("/api/v1/sync/status", {"ids": "x"}).status_code == 400


def test_submit_throttle(scenario, settings):
    settings.VTRS_THROTTLE_RATES = {**settings.VTRS_THROTTLE_RATES, "submit_device": "2/min"}
    for _ in range(2):
        scenario.submit(scenario.item())
    response = scenario.agent.client.post(
        "/api/v1/sync/submissions", {"items": [scenario.item()]}, format="json"
    )
    assert response.status_code == 429
    assert "Retry-After" in response


def test_head_selection():
    a, b, c = uuid7(), uuid7(), uuid7()
    assert select_head([(1, "SUBMITTED", a), (2, "REQUIRES_REVIEW", b)]) == b
    assert select_head([(1, "APPROVED", a), (2, "REJECTED", b)]) == a  # falls back
    assert select_head([(1, "REJECTED", a)]) is None
    assert select_head([(3, "SUBMITTED", c), (1, "SUBMITTED", a), (2, "REJECTED", b)]) == c
