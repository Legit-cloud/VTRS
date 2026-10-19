"""War room: every contestant side by side, drill-down, coverage, verification filter, ties and
narrow margins, history (FR-6.8.x, AC-09, AC-10, AC-14, AC-17)."""

import pytest

from apps.assignments.models import AgentAssignment
from apps.core.domain.permissions import Role
from apps.core.ids import uuid7
from apps.core.rls import system_context
from apps.geography.models import Constituency

from ..factories import make_ballot, make_election
from ..results.conftest import post_submission, seal

pytestmark = pytest.mark.django_db


def _dashboard(client, field, election=None, **query):
    return client.get(f"/api/v1/elections/{(election or field.election).id}/dashboard", query)


def _results(client, field, election=None, **query):
    return client.get(f"/api/v1/elections/{(election or field.election).id}/results", query)


def _votes(area):
    return {v["abbreviation"]: v["votes"] for v in area["votes"]}


@pytest.fixture
def busy(field_):
    """Votes (AAA, BBB) per polling unit: ward A1 has two, A2 one, B1 one, B2 none."""
    f = field_
    f.extra["a1"] = f.submit(f.pus_of(f.wards[0])[0], (100, 40))
    f.submit(f.pus_of(f.wards[0])[1], (20, 30))
    f.submit(f.pus_of(f.wards[1])[0], (10, 5))
    f.submit(f.pus_of(f.wards[2])[0], (7, 70))
    return f


def test_every_contestant_side_by_side_with_coverage(busy):
    body = _dashboard(busy.admin_client(), busy).json()
    assert body["provisional"] is True
    assert "not the official inec count" in body["notice"].lower()
    assert body["measure"] == "REPORTED"
    assert [p["abbreviation"] for p in body["parties"]] == ["AAA", "BBB"]
    summary = body["summary"]
    assert summary["level"] == "STATE"
    # "X of Y polling units reported" travels with the total.
    assert (summary["expected_pus"], summary["reported_pus"]) == (8, 4)
    assert summary["reported_pct"] == 50.0
    assert _votes(summary) == {"AAA": 137, "BBB": 145}
    # One constituency (the state): each party's row names its contestant.
    assert [v["candidate_name"] for v in summary["votes"]] == ["Candidate AAA", "Candidate BBB"]
    position = summary["position"]
    # BBB leads by 8 of 282 votes (2.8%): a narrow margin, said as such.
    assert position["status"] == "NARROW"
    assert position["leader_abbreviation"] == "BBB"
    assert position["margin"] == 8
    assert position["own_margin"] == -8  # AAA is the organization's own party


def test_ties_name_no_leader(field_):
    f = field_
    f.submit(f.pus[0], (50, 50))
    summary = _dashboard(f.admin_client(), f).json()["summary"]
    assert summary["position"]["status"] == "TIED"
    assert summary["position"]["leader_party_id"] is None
    assert set(summary["position"]["leading_party_ids"]) == {str(p.id) for p in f.parties}


def test_nothing_reported_yet(field_):
    summary = _dashboard(field_.admin_client(), field_).json()["summary"]
    assert summary["position"]["status"] == "NO_VOTES"
    assert (summary["expected_pus"], summary["reported_pus"]) == (8, 0)


def test_verified_only_filter(field_):
    f = field_
    approved = f.submit(f.pus[0], (60, 40))
    f.submit(f.pus[1], (10, 10))
    admin = f.admin_client()
    assert f.verify(approved, admin).status_code == 200
    reported = _dashboard(admin, f, measure="reported").json()["summary"]
    verified = _dashboard(admin, f, measure="verified").json()["summary"]
    assert (reported["reported_pus"], reported["verified_pus"]) == (2, 1)
    assert sum(reported["votes"][i]["votes"] for i in range(2)) == 120
    assert sum(verified["votes"][i]["votes"] for i in range(2)) == 100
    assert verified["counted_pus"] == 1
    assert _dashboard(admin, f, measure="bogus").status_code == 400
    assert _dashboard(admin, f, nope="1").status_code == 400


def test_the_election_policy_picks_the_default_measure(field_):
    from apps.elections.models import Election

    f = field_
    with system_context():
        Election.objects.filter(id=f.election.id).update(count_policy="VERIFIED")
    assert _dashboard(f.admin_client(), f).json()["measure"] == "VERIFIED"


def test_a_ward_coordinator_sees_only_their_ward(busy):
    ward = busy.wards[0]
    client = busy.officer_client(Role.WARD_OFFICER, ward)
    body = _dashboard(client, busy).json()
    summary = body["summary"]
    assert summary["level"] == "WARD"
    assert body["areas_in_scope"] == 1
    assert (summary["expected_pus"], summary["reported_pus"]) == (2, 2)
    assert _votes(summary) == {"AAA": 120, "BBB": 70}
    assert summary["position"]["status"] == "LEADING"


def test_an_lga_coordinator_sees_only_their_lga_and_never_the_state_total(busy):
    client = busy.officer_client(Role.LGA_OFFICER, busy.lgas[0])
    summary = _dashboard(client, busy).json()["summary"]
    assert summary["level"] == "LGA"
    assert (summary["expected_pus"], summary["reported_pus"]) == (4, 3)
    assert _votes(summary) == {"AAA": 130, "BBB": 75}
    assert _results(client, busy, level="state").json()["rows"] == []
    lga_rows = _results(client, busy, level="lga").json()["rows"]
    assert [r["area_id"] for r in lga_rows] == [str(busy.lgas[0].id)]


def test_drilling_down_from_state_to_polling_unit(busy):
    admin = busy.admin_client()
    lgas = _results(admin, busy, level="lga").json()["rows"]
    assert [r["level"] for r in lgas] == ["LGA", "LGA"]
    assert [(r["expected_pus"], r["reported_pus"]) for r in lgas] == [(4, 3), (4, 1)]
    # Every row has every party and its own leader.
    assert [r["position"]["leader_abbreviation"] for r in lgas] == ["AAA", "BBB"]
    assert all(len(r["votes"]) == 2 for r in lgas)

    lga = busy.lgas[0]
    wards = _results(admin, busy, level="ward", parent_id=str(lga.id)).json()["rows"]
    assert [(r["expected_pus"], r["reported_pus"]) for r in wards] == [(2, 2), (2, 1)]

    pus = _results(admin, busy, level="pu", parent_id=str(busy.wards[0].id)).json()["rows"]
    assert [r["status"] for r in pus] == ["SUBMITTED", "SUBMITTED"]
    # The polling unit's own leader.
    assert [r["position"]["leader_abbreviation"] for r in pus] == ["AAA", "BBB"]
    assert [r["verified"] for r in pus] == [False, False]
    assert [r["completion"] for r in pus] == ["NUMBERS_SUBMITTED", "NUMBERS_SUBMITTED"]
    empty = _results(admin, busy, level="pu", parent_id=str(busy.wards[1].id)).json()["rows"]
    assert [r["status"] for r in empty] == ["SUBMITTED", "NO_RESULT"]
    assert empty[0]["totals"]["valid"] == 15
    assert empty[1]["totals"]["valid"] is None
    assert empty[1]["position"]["status"] == "NO_VOTES"


def test_polling_unit_rows_show_verification(busy):
    admin = busy.admin_client()
    assert busy.verify(busy.extra["a1"], admin).status_code == 200
    pus = _results(admin, busy, level="pu", parent_id=str(busy.wards[0].id)).json()["rows"]
    assert [r["verified"] for r in pus] == [True, False]
    assert pus[0]["completion"] == "COMPLETE"
    verified_only = _results(
        admin, busy, level="pu", parent_id=str(busy.wards[0].id), measure="verified"
    ).json()["rows"]
    assert verified_only[1]["totals"]["valid"] is None  # unverified: not counted in this view


def test_drill_down_rules(busy):
    admin = busy.admin_client()
    assert _results(admin, busy, level="ward").status_code == 400  # needs the LGA
    assert _results(admin, busy, level="pu").status_code == 400  # needs the ward
    assert _results(admin, busy, level="galaxy").status_code == 400
    ward_officer = busy.officer_client(Role.WARD_OFFICER, busy.wards[0])
    sibling = busy.wards[1]
    assert _results(ward_officer, busy, level="pu", parent_id=str(sibling.id)).status_code == 404
    own = _results(ward_officer, busy, level="pu", parent_id=str(busy.wards[0].id))
    assert own.status_code == 200
    assert len(own.json()["rows"]) == 2


def test_agents_and_other_tenants_get_nothing(busy, make_org, make_member, client_as):
    agent = busy.agents[busy.pus[0].id].client
    assert _dashboard(agent, busy).status_code == 403
    assert _results(agent, busy).status_code == 403
    stranger = make_member(Role.PARTY_ADMIN, organization=make_org("Other Party"), mfa_enabled=True)
    outsider = client_as(stranger)
    assert _dashboard(outsider, busy).status_code == 404
    assert _results(outsider, busy).status_code == 404


def test_coverage_timeline_accumulates(busy):
    url = f"/api/v1/elections/{busy.election.id}/coverage-timeline"
    body = busy.admin_client().get(url, {"interval": "hour"}).json()
    assert body["expected_pus"] == 8
    assert body["points"][-1]["cumulative"] == 4
    assert sum(p["newly_reported"] for p in body["points"]) == 4
    assert busy.admin_client().get(url, {"interval": "week"}).status_code == 400


def test_the_first_read_builds_missing_rows(field_):
    from apps.aggregation.models import Rollup

    with system_context():
        assert Rollup.objects.filter(contest=field_.contest).count() == 0
    body = _dashboard(field_.admin_client(), field_).json()
    assert body["summary"]["expected_pus"] == 8
    with system_context():
        assert Rollup.objects.filter(contest=field_.contest).count() == 7


def test_several_constituencies_are_compared_by_party(field_):
    """An LGA chairmanship election: one contest per LGA, each with its own candidates. The
    state view sums each party across constituencies; an LGA row names its contestants."""
    f = field_
    election = make_election(f.org, f.admin, name="Chairmanship", type_code="LGA_CHAIRMANSHIP")
    ballots = []
    for lga in f.lgas:
        constituency = Constituency.objects.get(kind="LGA", code=lga.inec_code)
        ballots.append(
            make_ballot(f.org, election, own="AAA", constituency=constituency, parties=f.parties)
        )
    with system_context():
        for pu, agent in f.agents.items():
            unit = next(p for p in f.pus if p.id == pu)
            AgentAssignment.objects.create(
                organization=f.org,
                election=election,
                agent=agent.member.user,
                polling_unit=unit,
                ward_id=unit.ward_id,
                lga_id=unit.lga_id,
                assigned_by_id=f.admin.user.id,
            )

    def submit(pu, votes):
        ballot = ballots[[lg.id for lg in f.lgas].index(pu.lga_id)]
        item = f.item(pu, votes)
        item.update(
            election_id=str(election.id),
            votes=[
                {"candidate_id": str(c.id), "votes": v}
                for c, v in zip(ballot.candidates, votes, strict=True)
            ],
        )
        outcome = post_submission(f.agents[pu.id].client, seal(item))
        assert outcome["status"] == "ACCEPTED", outcome

    first_lga = [p for p in f.pus if p.lga_id == f.lgas[0].id]
    second_lga = [p for p in f.pus if p.lga_id == f.lgas[1].id]
    submit(first_lga[0], (30, 10))
    submit(second_lga[0], (5, 40))

    admin = f.admin_client()
    summary = _dashboard(admin, f, election=election).json()["summary"]
    assert _votes(summary) == {"AAA": 35, "BBB": 50}
    assert (summary["expected_pus"], summary["reported_pus"]) == (8, 2)
    # Across constituencies there is no single contestant per party.
    assert {v["candidate_name"] for v in summary["votes"]} == {None}
    rows = _results(admin, f, election=election, level="lga").json()["rows"]
    assert [r["position"]["leader_abbreviation"] for r in rows] == ["AAA", "BBB"]
    assert all(v["candidate_name"] == f"Candidate {v['abbreviation']}" for v in rows[0]["votes"])
    # The governorship election is unaffected.
    assert _dashboard(admin, f).json()["summary"]["reported_pus"] == 0


def test_a_polling_units_history_shows_every_version(field_):
    f = field_
    pu = f.pus[0]
    first = f.submit(pu, (100, 50))
    admin = f.admin_client()
    admin.post(
        f"/api/v1/results/{first['version_id']}/review",
        {"decision": "REJECTED", "reason": "Unreadable"},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid7()),
    )
    f.submit(pu, (101, 50), parent_version_id=first["version_id"])

    url = f"/api/v1/elections/{f.election.id}/polling-units/{pu.id}/history"
    body = admin.get(url).json()
    assert [v["version_no"] for v in body["versions"]] == [1, 2]
    assert [v["state"] for v in body["versions"]] == ["REJECTED", "SUBMITTED"]
    assert body["versions"][0]["reviews"][0]["reason"] == "Unreadable"
    assert body["versions"][1]["is_head"] is True
    assert body["head_version_id"] == body["versions"][1]["version_id"]
    assert [v["party_abbreviation"] for v in body["versions"][1]["votes"]] == ["AAA", "BBB"]
    expected_lat = float(pu.latitude or 7.39)
    assert float(body["versions"][0]["gps"]["lat"]) == pytest.approx(expected_lat, abs=1e-6)
    assert "evidence" in body["versions"][0]

    # Coordinators see their own area's sheets; nobody sees outside their area.
    ward_coordinator = f.officer_client(Role.WARD_OFFICER, f.wards[0])
    assert "evidence" in ward_coordinator.get(url).json()["versions"][0]
    elsewhere = f.officer_client(Role.WARD_OFFICER, f.wards[3])
    assert elsewhere.get(url).status_code == 404
    assert f.agents[pu.id].client.get(url).status_code == 403
