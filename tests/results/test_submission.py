"""Web submission (spec section 10; FR-6.5.x, FR-6.6.x, AC-05 - AC-08, AC-16).

Results are never duplicated and never silently dropped for being suspicious; invalid ones are
refused with a precise code; the form lists exactly the configured parties and the agent
cannot change that list; corrections are new versions; a result is complete only with its
sheet.
"""

import hashlib

import pytest
from django.db import DatabaseError, connection, transaction

from apps.anomalies.models import AnomalyFlag
from apps.audit.models import AuditEvent
from apps.core.ids import uuid7
from apps.core.models import OutboxEvent
from apps.core.rls import system_context
from apps.elections.models import Candidate, ConfigIssue, Election, Party
from apps.evidence.models import EvidenceFile
from apps.evidence.storage import get_storage
from apps.results.domain.sheet import arithmetic_problem, party_problem
from apps.results.domain.versions import VersionState, completion_of, select_head
from apps.results.models import PuResult, ResultVersion, VoteLine

from .conftest import PDF_BYTES, jpeg_bytes, manifest_entry, seal

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


# --- Accepting and idempotency (FR-6.6.6, AC-08) ---------------------------------------------


def test_accepted_submission(scenario):
    item = scenario.item()
    [outcome] = scenario.submit(item)
    assert outcome["status"] == "ACCEPTED", outcome
    assert (outcome["version_no"], outcome["is_head"], outcome["replayed"]) == (1, True, False)
    assert outcome["flags"] == []
    # Numbers are in; the sheet is not yet.
    assert outcome["completion"] == "NUMBERS_SUBMITTED"

    version = _version(item["version_id"])
    # Valid votes are the sum of the party votes, never entered separately.
    assert (version.valid, version.rejected, version.total_cast, version.accredited) == (
        200,
        5,
        205,
        210,
    )
    assert float(version.gps_lat) == pytest.approx(float(scenario.pu.latitude or 7.39), abs=1e-6)
    with system_context():
        lines = dict(
            VoteLine.objects.filter(result_version=version).values_list(
                "candidate__party__abbreviation", "votes"
            )
        )
        pu_result = PuResult.objects.get(election=scenario.election, polling_unit=scenario.pu)
    assert lines == {"AAA": 120, "BBB": 80}
    assert (pu_result.head_version_id, pu_result.status, pu_result.contest_id) == (
        version.id,
        "SUBMITTED",
        scenario.contest.id,
    )
    assert AuditEvent.objects.filter(
        action="result.version_accepted", object_id=str(version.id)
    ).exists()
    assert OutboxEvent.objects.filter(topic="result.version_accepted").count() == 1


def test_retries_and_double_taps_never_duplicate(scenario):
    """AC-08: the same submission id again returns the stored outcome; nothing new is written."""
    item = scenario.item()
    first = scenario.submit(item)[0]
    again = scenario.submit(item, item)
    assert [o["replayed"] for o in again] == [True, True]
    assert all(o["status"] == "ACCEPTED" and o["version_no"] == first["version_no"] for o in again)
    with system_context():
        assert ResultVersion.objects.filter(id=item["version_id"]).count() == 1
        assert PuResult.objects.get().version_count == 1


def test_same_submission_id_with_different_content_is_refused(scenario):
    item = scenario.item()
    scenario.submit(item)
    tampered = seal({**item, "votes": [{**item["votes"][0], "votes": 119}, item["votes"][1]]})
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


def test_one_result_per_polling_unit_per_election(scenario):
    """A second submission for the unit is a new version of the same result, never a second
    result."""
    scenario.submit(scenario.item())
    scenario.submit(scenario.item(votes=[130, 70]))
    with system_context():
        assert PuResult.objects.filter(polling_unit=scenario.pu).count() == 1
        assert ResultVersion.objects.count() == 2


# --- Validation (spec section 10.3) ----------------------------------------------------------


def test_blank_party_value_is_refused(scenario):
    item = scenario.item()
    blank = seal({**item, "votes": [{**item["votes"][0], "votes": None}, item["votes"][1]]})
    missing_key = seal({**item, "votes": [{"candidate_id": item["votes"][0]["candidate_id"]}]})
    outcomes = scenario.submit(blank, missing_key)
    assert [o["code"] for o in outcomes] == ["malformed", "malformed"]
    assert "votes" in outcomes[0]["errors"]
    with system_context():
        assert not ResultVersion.objects.exists()


def test_zero_votes_are_allowed(scenario):
    [outcome] = scenario.submit(scenario.item(votes=[0, 80]))
    assert outcome["status"] == "ACCEPTED"


def test_negative_and_non_integer_votes_are_refused(scenario):
    item = scenario.item()
    negative = seal({**item, "votes": [{**item["votes"][0], "votes": -1}, item["votes"][1]]})
    fraction = seal(
        {**scenario.item(), "votes": [{**item["votes"][0], "votes": 1.5}, item["votes"][1]]}
    )
    assert [o["code"] for o in scenario.submit(negative, fraction)] == ["malformed", "malformed"]


def test_unconfigured_party_is_refused(scenario, make_org):
    """A contestant from another constituency, another election or another organization is
    not on this form."""
    stranger = seal(
        {
            **scenario.item(),
            "votes": [
                {"candidate_id": str(scenario.candidates[0].id), "votes": 120},
                {"candidate_id": str(scenario.candidates[1].id), "votes": 80},
                {"candidate_id": str(uuid7()), "votes": 3},
            ],
        }
    )
    [outcome] = scenario.submit(stranger)
    assert (outcome["http_status"], outcome["code"]) == (400, "unconfigured_party")


def test_missing_party_is_refused(scenario):
    item = scenario.item()
    one_short = seal({**item, "votes": item["votes"][:1], "totals": {**item["totals"]}})
    [outcome] = scenario.submit(one_short)
    assert outcome["code"] == "missing_party"
    assert "BBB" in outcome["detail"]


def test_party_listed_twice_is_refused(scenario):
    item = scenario.item()
    twice = seal({**item, "votes": [item["votes"][0], item["votes"][0]]})
    [outcome] = scenario.submit(twice)
    assert outcome["code"] == "duplicate_party"


def test_totals_are_all_required(scenario):
    item = scenario.item()
    no_rejected = seal(
        {**item, "totals": {k: v for k, v in item["totals"].items() if k != "rejected"}}
    )
    with_valid = seal({**scenario.item(), "totals": {**item["totals"], "valid": 200}})
    outcomes = scenario.submit(no_rejected, with_valid)
    assert [o["code"] for o in outcomes] == ["malformed", "malformed"]


def test_party_votes_plus_rejected_must_not_exceed_total_cast(scenario):
    [outcome] = scenario.submit(
        scenario.item(
            votes=[120, 80], totals={"accredited": 300, "rejected": 10, "total_cast": 205}
        )
    )
    assert (outcome["http_status"], outcome["code"]) == (400, "votes_exceed_total_cast")
    assert "(200)" in outcome["detail"] and "(205)" in outcome["detail"]


def test_total_cast_must_not_exceed_accredited(scenario):
    [outcome] = scenario.submit(
        scenario.item(votes=[120, 80], totals={"accredited": 200, "rejected": 5, "total_cast": 205})
    )
    assert (outcome["http_status"], outcome["code"]) == (400, "total_cast_exceeds_accredited")


@pytest.mark.parametrize(
    ("change", "rule"),
    [
        # The sheet's totals do not reconcile: votes cast that no party received.
        (
            {"votes": [120, 80], "totals": {"accredited": 400, "rejected": 5, "total_cast": 300}},
            "ARITHMETIC_VARIANCE",
        ),
        # More accredited than registered.
        (
            {
                "votes": [600, 500],
                "totals": {"accredited": 1200, "rejected": 0, "total_cast": 1100},
            },
            "OVER_VOTING",
        ),
    ],
)
def test_suspicious_results_are_accepted_and_flagged(scenario, change, rule):
    """Never silently dropped for looking wrong: stored, flagged, routed to review."""
    item = scenario.item(**change)
    [outcome] = scenario.submit(item)
    assert outcome["status"] == "REQUIRES_REVIEW", outcome
    assert rule in outcome["flags"]
    assert _version(item["version_id"]).state == VersionState.REQUIRES_REVIEW
    assert rule in _flags(item["version_id"])


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
    [outcome] = scenario.submit(scenario.item())
    assert outcome["status"] == "REQUIRES_REVIEW"
    assert outcome["flags"] == ["LATE_SUBMISSION"]


def test_config_version_mismatch_is_flagged(scenario):
    [outcome] = scenario.submit(scenario.item(config_version=4))
    assert outcome["flags"] == ["CONFIG_VERSION_MISMATCH"]


def test_unit_without_a_configured_contest_is_refused(scenario):
    """An election type whose constituency for the unit has no contestants yet."""
    with system_context():
        Candidate.objects.filter(contest=scenario.contest).delete()
        scenario.contest.delete()
    [outcome] = scenario.submit(scenario.item())
    assert (outcome["http_status"], outcome["code"]) == (409, "no_contest_for_polling_unit")


# --- Versioned corrections (FR-6.7.5) --------------------------------------------------------


def test_corrections_are_new_versions(scenario):
    first = scenario.item()
    scenario.submit(first)
    correction = scenario.item(parent_version_id=first["version_id"], votes=[121, 80])
    [outcome] = scenario.submit(correction)
    assert (outcome["status"], outcome["version_no"], outcome["is_head"]) == ("ACCEPTED", 2, True)
    assert _version(first["version_id"]).valid == 200  # the original is never edited
    with system_context():
        assert PuResult.objects.get().head_version_id == _version(correction["version_id"]).id
        assert ResultVersion.objects.count() == 2


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
    with system_context(), connection.cursor() as cursor:
        cursor.execute(
            "UPDATE result_version SET state = 'APPROVED' WHERE id = %s", [item["version_id"]]
        )
    as_superuser()
    refused("UPDATE result_version SET valid = 999 WHERE id = %s")


# --- The result form (FR-6.5.1, AC-16) --------------------------------------------------------


def _form(scenario, client=None, pu=None):
    client = client or scenario.agent.client
    return client.get(
        f"/api/v1/elections/{scenario.election.id}/polling-units/{(pu or scenario.pu).id}/form"
    )


def test_form_lists_exactly_the_configured_parties_in_order(scenario):
    """Parties in the admin's order with their candidates. A party in the master list that is
    not contesting, and a contestant in another constituency, are not on the form."""
    with system_context():
        Party.objects.create(organization=scenario.org, full_name="Idle Party", abbreviation="IDL")
    response = _form(scenario)
    assert response.status_code == 200, response.content
    body = response.json()
    assert [p["party_abbreviation"] for p in body["parties"]] == ["AAA", "BBB"]
    assert [p["candidate_name"] for p in body["parties"]] == ["Candidate AAA", "Candidate BBB"]
    assert [p["ballot_order"] for p in body["parties"]] == [1, 2]
    assert body["totals"] == ["accredited", "rejected", "total_cast"]
    assert body["constituency"]["id"] == str(scenario.contest.constituency_id)
    assert body["config_version"] == scenario.election.config_version
    assert body["current"] is None


def test_form_follows_the_admin_order(scenario):
    with system_context():
        from apps.elections.models import ElectionParty

        entries = list(ElectionParty.objects.filter(election=scenario.election))
        ElectionParty.objects.filter(election=scenario.election).delete()
        for entry, order in zip(entries, (2, 1), strict=True):
            ElectionParty.objects.create(
                organization=scenario.org,
                election=scenario.election,
                party_id=entry.party_id,
                ballot_order=order,
            )
    assert [p["party_abbreviation"] for p in _form(scenario).json()["parties"]] == ["BBB", "AAA"]


def test_form_only_for_assigned_units(scenario):
    assert _form(scenario, pu=scenario.other_pu).status_code == 404
    unassigned = scenario.make_agent(assign=False)
    assert _form(scenario, client=unassigned.client).status_code == 404


def test_form_shows_the_current_result_for_corrections(scenario):
    item = scenario.item()
    scenario.submit(item)
    current = _form(scenario).json()["current"]
    assert current["version_id"] == item["version_id"]
    assert current["completion"] == "NUMBERS_SUBMITTED"
    assert current["totals"] == {"accredited": 210, "rejected": 5, "total_cast": 205}
    assert current["votes"] == {
        str(scenario.candidates[0].id): 120,
        str(scenario.candidates[1].id): 80,
    }


def test_agent_cannot_alter_the_party_list(scenario):
    """Parties and contestants are master data: agents can neither change them through the
    admin endpoints nor smuggle a new one in through a submission."""
    client = scenario.agent.client
    party = scenario.candidates[0].party
    assert client.post(
        "/api/v1/parties", {"full_name": "New", "abbreviation": "NEW"}, format="json"
    ).status_code in {403, 404}
    assert client.patch(
        f"/api/v1/parties/{party.id}", {"abbreviation": "ZZZ"}, format="json"
    ).status_code in {403, 404}
    assert client.delete(f"/api/v1/parties/{party.id}").status_code in {403, 404}
    assert client.put(
        f"/api/v1/elections/{scenario.election.id}/parties",
        {"party_ids": [str(party.id)]},
        format="json",
    ).status_code in {403, 404}
    assert client.post(
        f"/api/v1/elections/{scenario.election.id}/contestants",
        {
            "constituency_id": str(scenario.contest.constituency_id),
            "party_id": str(party.id),
            "name": "Someone else",
        },
        format="json",
    ).status_code in {403, 404}
    assert client.patch(
        f"/api/v1/contestants/{scenario.candidates[0].id}", {"name": "Renamed"}, format="json"
    ).status_code in {403, 404}
    with system_context():
        assert Party.objects.filter(organization=scenario.org).count() == 2
        assert sorted(Candidate.objects.values_list("name", flat=True)) == [
            "Candidate AAA",
            "Candidate BBB",
        ]
    assert [p["party_abbreviation"] for p in _form(scenario).json()["parties"]] == ["AAA", "BBB"]


# --- "Party or contestant missing" (FR-6.3.7) ---------------------------------------------


def test_agent_reports_a_missing_party_as_a_task(scenario):
    response = scenario.agent.client.post(
        f"/api/v1/elections/{scenario.election.id}/config-issues",
        {
            "polling_unit_id": str(scenario.pu.id),
            "kind": "PARTY_MISSING",
            "note": "ZZP is on the sheet",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid7()),
    )
    assert response.status_code == 201, response.content
    assert response.json()["status"] == "OPEN"
    with system_context():
        assert ConfigIssue.objects.get().kind == "PARTY_MISSING"
        # A task, never a party or contestant.
        assert Party.objects.filter(organization=scenario.org).count() == 2
        assert Candidate.objects.count() == 2
    assert AuditEvent.objects.filter(action="config_issue.raised").exists()


def test_missing_party_report_only_for_assigned_units(scenario):
    response = scenario.agent.client.post(
        f"/api/v1/elections/{scenario.election.id}/config-issues",
        {
            "polling_unit_id": str(scenario.other_pu.id),
            "kind": "CONTESTANT_MISSING",
            "note": "x y z",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid7()),
    )
    assert response.status_code == 404


def test_admin_lists_and_resolves_issues(scenario, client_as):
    scenario.agent.client.post(
        f"/api/v1/elections/{scenario.election.id}/config-issues",
        {"polling_unit_id": str(scenario.pu.id), "kind": "CONTESTANT_MISSING", "note": "No name"},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid7()),
    )
    admin = client_as(scenario.admin)
    listed = admin.get(f"/api/v1/elections/{scenario.election.id}/config-issues?status=OPEN")
    assert listed.status_code == 200
    [issue] = listed.json()["results"]
    assert issue["polling_unit_code"] == scenario.pu.inec_code
    resolved = admin.post(
        f"/api/v1/config-issues/{issue['id']}/resolve",
        {"note": "Added the candidate before lock"},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid7()),
    )
    assert resolved.status_code == 200 and resolved.json()["status"] == "RESOLVED"
    # The agent cannot read the admin queue.
    assert (
        scenario.agent.client.get(
            f"/api/v1/elections/{scenario.election.id}/config-issues"
        ).status_code
        == 403
    )


# --- Status and completion (FR-6.6.5) --------------------------------------------------------


def _upload_sheet(scenario, version_id, data, mime):
    entry = {**manifest_entry(data, mime=mime), "version_id": version_id}
    requested = scenario.agent.client.post("/api/v1/evidence/uploads", entry, format="json")
    assert requested.status_code == 200, requested.content
    with system_context():
        key = EvidenceFile.objects.get(id=entry["evidence_id"]).object_key
    get_storage().write(key, data, mime=mime)
    done = scenario.agent.client.post(f"/api/v1/evidence/{entry['evidence_id']}/complete")
    assert done.status_code == 200, done.content
    return done.json()


@pytest.mark.parametrize(
    ("data", "mime"), [(jpeg_bytes(), "image/jpeg"), (PDF_BYTES, "application/pdf")]
)
def test_submission_is_complete_once_the_sheet_is_attached(scenario, data, mime):
    item = scenario.item()
    scenario.submit(item)
    status = scenario.agent.client.get(f"/api/v1/submissions/{item['version_id']}").json()
    assert status["completion"] == "NUMBERS_SUBMITTED"

    done = _upload_sheet(scenario, item["version_id"], data, mime)
    assert done["completion"] == "COMPLETE"
    status = scenario.agent.client.get(f"/api/v1/submissions/{item['version_id']}").json()
    assert status["completion"] == "COMPLETE"
    assert status["evidence"][0]["mime"] == mime
    assert hashlib.sha256(data).hexdigest()  # the declared hash pins the upload


def test_my_assignments_show_the_result_state(scenario):
    rows = scenario.agent.client.get("/api/v1/me/assignments").json()
    assert [r["polling_unit"]["id"] for r in rows] == [str(scenario.pu.id)]
    assert rows[0]["result"] is None
    item = scenario.item()
    scenario.submit(item)
    [row] = scenario.agent.client.get("/api/v1/me/assignments").json()
    assert row["result"]["version_id"] == item["version_id"]
    assert row["my_latest"]["completion"] == "NUMBERS_SUBMITTED"


def test_status_of_someone_elses_submission_is_not_found(scenario):
    other_agent = scenario.make_agent()
    theirs = scenario.item(agent=other_agent)
    scenario.submit(theirs, agent=other_agent)
    assert (
        scenario.agent.client.get(f"/api/v1/submissions/{theirs['version_id']}").status_code == 404
    )


def test_submit_throttle(scenario, settings):
    settings.VTRS_THROTTLE_RATES = {**settings.VTRS_THROTTLE_RATES, "submit_agent": "2/min"}
    for _ in range(2):
        scenario.submit(scenario.item())
    response = scenario.agent.client.post("/api/v1/submissions", scenario.item(), format="json")
    assert response.status_code == 429
    assert "Retry-After" in response


# --- Pure rules ------------------------------------------------------------------------------


def test_head_selection():
    a, b, c = uuid7(), uuid7(), uuid7()
    assert select_head([(1, "SUBMITTED", a), (2, "REQUIRES_REVIEW", b)]) == b
    assert select_head([(1, "APPROVED", a), (2, "REJECTED", b)]) == a  # falls back
    assert select_head([(1, "REJECTED", a)]) is None
    assert select_head([(3, "SUBMITTED", c), (1, "SUBMITTED", a), (2, "REJECTED", b)]) == c


def test_party_rules():
    a, b, c = uuid7(), uuid7(), uuid7()
    labels = {a: "AAA", b: "BBB"}
    assert party_problem([a, b], {a, b}, labels) is None
    assert party_problem([a], {a, b}, labels).code == "missing_party"
    assert "BBB" in party_problem([a], {a, b}, labels).detail
    assert party_problem([a, b, c], {a, b}, labels).code == "unconfigured_party"
    assert party_problem([a, a, b], {a, b}, labels).code == "duplicate_party"


def test_arithmetic_rules():
    ok = {"accredited": 210, "rejected": 5, "total_cast": 205}
    assert arithmetic_problem(200, ok) is None
    assert arithmetic_problem(199, ok) is None  # short of total cast: flagged, not refused
    assert arithmetic_problem(201, ok).code == "votes_exceed_total_cast"
    assert (
        arithmetic_problem(200, {**ok, "accredited": 204}).code == "total_cast_exceeds_accredited"
    )


def test_completion_rule():
    assert completion_of([]) == "NUMBERS_SUBMITTED"
    assert completion_of(["PENDING_UPLOAD"]) == "NUMBERS_SUBMITTED"
    assert completion_of(["QUARANTINED"]) == "NUMBERS_SUBMITTED"
    assert completion_of(["PENDING_UPLOAD", "UPLOADED"]) == "COMPLETE"
    assert completion_of(["VERIFIED"]) == "COMPLETE"
