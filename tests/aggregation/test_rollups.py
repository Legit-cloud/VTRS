"""PU -> Ward -> LGA -> State aggregation (FR-6.7.1, FR-6.7.2, AC-09, AC-10, DD-05)."""

import pytest

from apps.aggregation import services
from apps.aggregation.models import Rollup
from apps.core.models import OutboxEvent
from apps.core.rls import system_context
from apps.elections.models import Election

pytestmark = pytest.mark.django_db


def _row(field, level, area_id):
    with system_context():
        return Rollup.objects.get(contest=field.contest, level=level, area_id=area_id)


def _votes(row):
    return {
        v.candidate.party.abbreviation: v.reported_votes
        for v in row.votes.select_related("candidate__party")
    }


def test_results_roll_up_to_ward_lga_and_state(field_):
    ward_a1, ward_a2, ward_b1, _ = field_.wards
    lga_a, lga_b = field_.lgas
    pu_a1 = field_.pus_of(ward_a1)
    field_.submit(pu_a1[0], (100, 50))
    field_.submit(pu_a1[1], (30, 20))
    field_.submit(field_.pus_of(ward_a2)[0], (10, 5))
    field_.submit(field_.pus_of(ward_b1)[0], (7, 3))

    with system_context():
        assert _votes(_row(field_, "WARD", ward_a1.id)) == {"AAA": 130, "BBB": 70}
        assert _votes(_row(field_, "WARD", ward_a2.id)) == {"AAA": 10, "BBB": 5}
        assert _votes(_row(field_, "LGA", lga_a.id)) == {"AAA": 140, "BBB": 75}
        assert _votes(_row(field_, "LGA", lga_b.id)) == {"AAA": 7, "BBB": 3}
        state = _row(field_, "STATE", field_.election.state_id)
        assert _votes(state) == {"AAA": 147, "BBB": 78}
        assert state.reported_valid == 147 + 78
        assert state.reported_pus == 4


def test_expected_versus_reported_polling_units(field_):
    ward_a1 = field_.wards[0]
    field_.submit(field_.pus_of(ward_a1)[0])
    with system_context():
        state = _row(field_, "STATE", field_.election.state_id)
        ward = _row(field_, "WARD", ward_a1.id)
        assert (state.expected_pus, state.reported_pus) == (8, 1)
        assert (ward.expected_pus, ward.reported_pus) == (2, 1)
        assert state.registered_voters == sum(range(500, 508))


def test_a_correction_replaces_the_old_figures_it_does_not_add_to_them(field_):
    pu = field_.pus[0]
    first = field_.submit(pu, (100, 50))
    field_.submit(pu, (110, 50), parent_version_id=first["version_id"])
    with system_context():
        state = _row(field_, "STATE", field_.election.state_id)
        assert _votes(state) == {"AAA": 110, "BBB": 50}
        assert state.reported_pus == 1


def test_a_replayed_submission_changes_nothing(field_):
    pu = field_.pus[0]
    outcome = field_.submit(pu, (100, 50))
    before = _row(field_, "STATE", field_.election.state_id).revision
    again = field_.agents[pu.id].client.post("/api/v1/submissions", outcome["item"], format="json")
    assert again.json()["replayed"] is True
    state = _row(field_, "STATE", field_.election.state_id)
    assert _votes(state) == {"AAA": 100, "BBB": 50}
    assert state.revision == before  # a replay emits no event


def test_flagged_results_count_and_are_marked_for_review(field_):
    pu = field_.pus[0]
    # Party votes (150) plus rejected (5) fall short of total cast (175): flagged, still counted.
    outcome = field_.submit(
        pu, (100, 50), totals={"accredited": 400, "rejected": 5, "total_cast": 175}
    )
    assert outcome["status"] == "REQUIRES_REVIEW"
    with system_context():
        state = _row(field_, "STATE", field_.election.state_id)
        assert state.reported_pus == 1
        assert state.review_pus == 1
        assert state.open_flags >= 1
        assert _votes(state) == {"AAA": 100, "BBB": 50}


def test_verify_reconciles_a_busy_election_and_detects_tampering(field_):
    for index, pu in enumerate(field_.pus):
        field_.submit(pu, (40 + index, 25 + 2 * index))
    with system_context():
        assert services.verify_contest(field_.contest) == []
        state = _row(field_, "STATE", field_.election.state_id)
        Rollup.objects.filter(id=state.id).update(reported_valid=1)
        problems = services.verify_contest(field_.contest)
        assert any("reported_valid" in p for p in problems)
    # A rebuild repairs it.
    services.rebuild_contest(organization_id=field_.org.id, contest_id=field_.contest.id)
    with system_context():
        assert services.verify_contest(field_.contest) == []


def test_recomputing_twice_is_harmless(field_):
    pu = field_.pus[0]
    field_.submit(pu, (60, 40))
    args = {
        "organization_id": field_.org.id,
        "contest_id": field_.contest.id,
        "ward_id": pu.ward_id,
    }
    services.recompute_ward(**args)
    services.recompute_ward(**args)
    with system_context():
        assert services.verify_contest(field_.contest) == []
        assert _votes(_row(field_, "STATE", field_.election.state_id)) == {"AAA": 60, "BBB": 40}


def test_going_live_builds_every_row_before_the_first_result(
    make_org, make_member, client_as, django_capture_on_commit_callbacks
):
    from .conftest import build_field

    field = build_field(make_org, make_member, client_as, django_capture_on_commit_callbacks)
    with system_context():
        assert Rollup.objects.filter(contest=field.contest).count() == 0
        Election.objects.filter(id=field.election.id).update(status="LOCKED")
    response = field.admin_client().post(
        f"/api/v1/elections/{field.election.id}/transition", {"to": "LIVE"}, format="json"
    )
    assert response.status_code == 200, response.content
    with system_context():
        levels = list(Rollup.objects.filter(contest=field.contest).values_list("level", flat=True))
        assert sorted(levels) == ["LGA", "LGA", "STATE"] + ["WARD"] * 4
        assert OutboxEvent.objects.filter(topic="election.opened").exists()


def test_operator_commands_detect_and_repair_drift(field_):
    from django.core.management import call_command
    from django.core.management.base import CommandError

    field_.submit(field_.pus[0], (60, 40))
    call_command("verify_rollups", "--election", str(field_.election.id))
    with system_context():
        Rollup.objects.filter(contest=field_.contest, level="STATE").update(reported_valid=3)
    with pytest.raises(CommandError, match="difference"):
        call_command("verify_rollups", "--election", str(field_.election.id))
    call_command("rebuild_rollups", "--contest", str(field_.contest.id))
    call_command("verify_rollups", "--election", str(field_.election.id))
