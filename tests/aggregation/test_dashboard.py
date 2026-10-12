"""War Room, drill-down, coverage and history reads (FR-6.8.x, AC-09, AC-10, AC-14)."""

import pytest

from apps.core.domain.permissions import Role
from apps.core.ids import uuid7
from apps.core.rls import system_context

pytestmark = pytest.mark.django_db


def _dashboard(client, field, **query):
    return client.get(f"/api/v1/elections/{field.election.id}/dashboard", query)


def _results(client, field, **query):
    return client.get(f"/api/v1/contests/{field.contest.id}/results", query)


@pytest.fixture
def busy(field_):
    """Votes (AAA, BBB) per polling unit: ward A1 has two, A2 one, B1 one, B2 none."""
    f = field_
    f.submit(f.pus_of(f.wards[0])[0], (100, 40))
    f.submit(f.pus_of(f.wards[0])[1], (20, 30))
    f.submit(f.pus_of(f.wards[1])[0], (10, 5))
    f.submit(f.pus_of(f.wards[2])[0], (7, 70))
    return f


def test_the_war_room_shows_a_provisional_position(busy):
    body = _dashboard(busy.admin_client(), busy).json()
    assert body["provisional"] is True
    assert "not an official declaration" in body["notice"].lower()
    assert body["measure"] == "REPORTED"
    [contest] = body["contests"]
    assert contest["level"] == "STATE"
    assert (contest["expected_pus"], contest["reported_pus"]) == (8, 4)
    assert contest["reported_pct"] == 50.0
    assert {v["party_acronym"]: v["votes"] for v in contest["votes"]} == {"AAA": 137, "BBB": 145}
    position = contest["position"]
    assert position["leader_party"] == "BBB"
    assert position["margin"] == 8
    assert position["own_margin"] == -8  # AAA is the organization's own candidate
    assert position["is_tie"] is False


def test_measure_selects_reported_or_verified(reviewed_field):
    f = reviewed_field
    approved = f.submit(f.pus[0], (60, 40))
    f.submit(f.pus[1], (10, 10))
    admin = f.admin_client()
    admin.post(
        f"/api/v1/results/{approved['version_id']}/review",
        {"decision": "APPROVED"},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid7()),
    )
    reported = _dashboard(admin, f, measure="reported").json()["contests"][0]
    verified = _dashboard(admin, f, measure="verified").json()["contests"][0]
    assert (reported["reported_pus"], reported["verified_pus"]) == (2, 1)
    assert sum(v["votes"] for v in reported["votes"]) == 120
    assert sum(v["votes"] for v in verified["votes"]) == 100
    assert verified["counted_pus"] == 1
    assert _dashboard(admin, f, measure="bogus").status_code == 400
    assert _dashboard(admin, f, nope="1").status_code == 400


def test_the_election_policy_picks_the_default_measure(reviewed_field):
    from apps.elections.models import Election

    f = reviewed_field
    with system_context():
        Election.objects.filter(id=f.election.id).update(count_policy="VERIFIED")
    assert _dashboard(f.admin_client(), f).json()["measure"] == "VERIFIED"


def test_a_ward_officer_sees_only_their_ward(busy):
    ward = busy.wards[0]
    client = busy.officer_client(Role.WARD_OFFICER, ward)
    [contest] = _dashboard(client, busy).json()["contests"]
    assert contest["level"] == "WARD"
    assert contest["areas_in_scope"] == 1
    assert (contest["expected_pus"], contest["reported_pus"]) == (2, 2)
    assert {v["party_acronym"]: v["votes"] for v in contest["votes"]} == {"AAA": 120, "BBB": 70}


def test_an_lga_officer_sees_only_their_lga_and_never_the_state_total(busy):
    client = busy.officer_client(Role.LGA_OFFICER, busy.lgas[0])
    [contest] = _dashboard(client, busy).json()["contests"]
    assert contest["level"] == "LGA"
    assert (contest["expected_pus"], contest["reported_pus"]) == (4, 3)
    assert {v["party_acronym"]: v["votes"] for v in contest["votes"]} == {"AAA": 130, "BBB": 75}
    state = _results(client, busy, level="state").json()
    assert state["rows"] == []  # above their own level: nothing, and nothing revealed


def test_drilling_down_from_state_to_polling_unit(busy):
    admin = busy.admin_client()
    lgas = _results(admin, busy, level="lga").json()["rows"]
    assert [r["level"] for r in lgas] == ["LGA", "LGA"]
    assert [(r["expected_pus"], r["reported_pus"]) for r in lgas] == [(4, 3), (4, 1)]

    lga = busy.lgas[0]
    wards = _results(admin, busy, level="ward", parent_id=str(lga.id)).json()["rows"]
    assert [(r["expected_pus"], r["reported_pus"]) for r in wards] == [(2, 2), (2, 1)]

    pus = _results(admin, busy, level="pu", parent_id=str(busy.wards[1].id)).json()["rows"]
    assert [r["status"] for r in pus] == ["SUBMITTED", "NO_RESULT"]
    assert pus[0]["totals"]["valid"] == 15
    assert pus[1]["totals"]["valid"] is None
    assert pus[1]["position"]["leader_id"] is None


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
    body = (
        busy.admin_client()
        .get(f"/api/v1/contests/{busy.contest.id}/coverage-timeline", {"interval": "hour"})
        .json()
    )
    assert body["expected_pus"] == 8
    assert body["points"][-1]["cumulative"] == 4
    assert sum(p["newly_reported"] for p in body["points"]) == 4
    bad = busy.admin_client().get(
        f"/api/v1/contests/{busy.contest.id}/coverage-timeline", {"interval": "week"}
    )
    assert bad.status_code == 400


def test_the_first_read_builds_missing_rows(field_):
    from apps.aggregation.models import Rollup

    with system_context():
        assert Rollup.objects.filter(contest=field_.contest).count() == 0
    body = _dashboard(field_.admin_client(), field_).json()
    assert body["contests"][0]["expected_pus"] == 8
    with system_context():
        assert Rollup.objects.filter(contest=field_.contest).count() == 7


def test_a_polling_units_history_shows_every_version(reviewed_field):
    f = reviewed_field
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

    url = f"/api/v1/contests/{f.contest.id}/polling-units/{pu.id}/history"
    body = admin.get(url).json()
    assert [v["version_no"] for v in body["versions"]] == [1, 2]
    assert [v["state"] for v in body["versions"]] == ["REJECTED", "SUBMITTED"]
    assert body["versions"][0]["reviews"][0]["reason"] == "Unreadable"
    assert body["versions"][1]["is_head"] is True
    assert body["head_version_id"] == body["versions"][1]["version_id"]
    expected_lat = float(pu.latitude or 7.39)
    assert float(body["versions"][0]["gps"]["lat"]) == pytest.approx(expected_lat, abs=1e-6)
    assert "evidence" in body["versions"][0]  # an admin holds evidence.view

    ward_officer = f.officer_client(Role.WARD_OFFICER, f.wards[0])
    officer_body = ward_officer.get(url).json()
    assert "evidence" not in officer_body["versions"][0]  # no evidence.view without a grant
    assert officer_body["versions"][0]["evidence_count"] == 0
    elsewhere = f.officer_client(Role.WARD_OFFICER, f.wards[3])
    assert elsewhere.get(url).status_code == 404
    assert f.agents[pu.id].client.get(url).status_code == 403
