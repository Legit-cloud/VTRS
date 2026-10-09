"""AC-03: admins deploy agents to polling units. AC-04 / FR-6.2.5: the agent sees only their
own assignments, with the ballot for each, before capture."""

import pytest

from apps.assignments.selectors import active_assignment
from apps.audit.models import AuditEvent
from apps.core.domain.actor import Actor, Scope, ScopeKind
from apps.core.domain.permissions import Role
from apps.core.rls import set_tenant, system_context
from apps.elections.models import Candidate, Contest, Election
from apps.geography.domain.synthetic import synthetic_master_data
from apps.geography.models import Lga, PollingUnit, State, Ward
from apps.geography.services import import_master_data

pytestmark = pytest.mark.django_db
KEY = iter(range(1, 10_000))


@pytest.fixture
def geo():
    import_master_data(synthetic_master_data(lgas=2, wards=4, polling_units=8))
    lga_a, lga_b = Lga.objects.order_by("inec_code")
    return {
        "state": State.objects.get(),
        "lga_a": lga_a,
        "lga_b": lga_b,
        "pu_a": PollingUnit.objects.filter(lga=lga_a).order_by("inec_code").first(),
        "pu_a2": PollingUnit.objects.filter(lga=lga_a).order_by("inec_code").last(),
        "pu_b": PollingUnit.objects.filter(lga=lga_b).order_by("inec_code").first(),
    }


@pytest.fixture
def admin(make_member):
    return make_member(Role.PARTY_ADMIN)


@pytest.fixture
def client(admin, client_as):
    return client_as(admin)


def _election(org, geo, status="LOCKED"):
    """A governorship (whole state) plus an assembly seat covering LGA A only."""
    with system_context():
        election = Election.objects.create(
            organization=org,
            name=f"Election {next(KEY)}",
            state=geo["state"],
            election_date="2027-03-11",
            status=status,
            created_by_id=org.id,
        )
        for title, level, ids in (
            ("Governor", "STATE", [geo["state"].id]),
            ("Assembly A", "LGA", [geo["lga_a"].id]),
        ):
            contest = Contest.objects.create(
                organization=org,
                election=election,
                office="OTHER",
                title=title,
                jurisdiction_level=level,
                jurisdiction_ids=ids,
            )
            for order, acronym in ((2, "BBB"), (1, "AAA")):
                Candidate.objects.create(
                    organization=org,
                    contest=contest,
                    name=f"{title} {acronym}",
                    party_name=acronym,
                    party_acronym=acronym,
                    ballot_order=order,
                    config_version=1,
                )
    return election


def _assign(client, election, agent, pu):
    return client.post(
        "/api/v1/assignments",
        {
            "election_id": str(election.id),
            "agent_id": str(agent.user.id),
            "polling_unit_id": str(pu.id),
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=f"a-{next(KEY)}",
    )


def test_deploy_and_agent_view(admin, client, client_as, make_member, geo):
    election = _election(admin.organization, geo)
    agent = make_member(
        Role.PU_AGENT, scope_ids=[geo["pu_a"].id, geo["pu_b"].id], organization=admin.organization
    )

    created = _assign(client, election, agent, geo["pu_a"])
    assert created.status_code == 201, created.json()
    assert created.json()["ward_id"] == str(geo["pu_a"].ward_id)
    assert AuditEvent.objects.filter(action="assignment.created").exists()
    _assign(client, election, agent, geo["pu_b"])

    mine = client_as(agent).get("/api/v1/me/assignments").json()
    by_pu = {row["polling_unit"]["inec_code"]: row for row in mine}
    assert set(by_pu) == {geo["pu_a"].inec_code, geo["pu_b"].inec_code}

    in_a = by_pu[geo["pu_a"].inec_code]
    assert in_a["election"]["status"] == "LOCKED"
    assert in_a["election"]["capture_open"] is False
    # PU in LGA A gets both contests; PU in LGA B only the governorship.
    assert sorted(c["title"] for c in in_a["contests"]) == ["Assembly A", "Governor"]
    assert [c["title"] for c in by_pu[geo["pu_b"].inec_code]["contests"]] == ["Governor"]
    # Candidates come in ballot order.
    assert [k["ballot_order"] for k in in_a["contests"][0]["candidates"]] == [1, 2]


def test_agents_see_only_their_own_assignments(admin, client, client_as, make_member, geo):
    election = _election(admin.organization, geo)
    org = admin.organization
    mine = make_member(Role.PU_AGENT, scope_ids=[geo["pu_a"].id], organization=org)
    theirs = make_member(Role.PU_AGENT, scope_ids=[geo["pu_a2"].id], organization=org)
    _assign(client, election, mine, geo["pu_a"])
    _assign(client, election, theirs, geo["pu_a2"])
    rows = client_as(mine).get("/api/v1/me/assignments").json()
    assert [r["polling_unit"]["id"] for r in rows] == [str(geo["pu_a"].id)]


def test_capture_opens_when_live_and_assignments_disappear_when_closed(
    admin, client, client_as, make_member, geo
):
    election = _election(admin.organization, geo, status="LIVE")
    agent = make_member(Role.PU_AGENT, scope_ids=[geo["pu_a"].id], organization=admin.organization)
    _assign(client, election, agent, geo["pu_a"])
    agent_client = client_as(agent)
    assert agent_client.get("/api/v1/me/assignments").json()[0]["election"]["capture_open"] is True
    with system_context():
        Election.objects.filter(id=election.id).update(status="CLOSED")
    assert agent_client.get("/api/v1/me/assignments").json() == []


@pytest.mark.parametrize(
    ("case", "field"),
    [
        ("outside_agent_scope", "polling_unit_id"),
        ("unknown_polling_unit", "polling_unit_id"),
        ("not_an_agent", "agent_id"),
    ],
)
def test_assignment_validation(admin, client, make_member, geo, case, field):
    election = _election(admin.organization, geo)
    agent = make_member(Role.PU_AGENT, scope_ids=[geo["pu_a"].id], organization=admin.organization)
    officer = make_member(Role.WARD_OFFICER, organization=admin.organization)
    body = {
        "election_id": str(election.id),
        "agent_id": str(agent.user.id),
        "polling_unit_id": str(geo["pu_a"].id),
    }
    if case == "outside_agent_scope":
        body["polling_unit_id"] = str(geo["pu_b"].id)
    elif case == "unknown_polling_unit":
        body["polling_unit_id"] = "0190a6a0-0000-7000-8000-000000000000"
    else:
        body["agent_id"] = str(officer.user.id)
    response = client.post("/api/v1/assignments", body, format="json", HTTP_IDEMPOTENCY_KEY=case)
    assert response.status_code == 400
    assert field in response.json()["errors"]


def test_agents_from_another_organization_do_not_exist(admin, client, make_member, geo):
    election = _election(admin.organization, geo)
    outsider = make_member(Role.PU_AGENT, scope_ids=[geo["pu_a"].id])
    assert _assign(client, election, outsider, geo["pu_a"]).status_code == 404


def test_duplicates_and_the_per_unit_cap(admin, client, make_member, geo, settings):
    election = _election(admin.organization, geo)
    org = admin.organization
    first = make_member(Role.PU_AGENT, scope_ids=[geo["pu_a"].id], organization=org)
    second = make_member(Role.PU_AGENT, scope_ids=[geo["pu_a"].id], organization=org)
    assert _assign(client, election, first, geo["pu_a"]).status_code == 201
    assert _assign(client, election, first, geo["pu_a"]).json()["code"] == "already_assigned"
    assert (
        _assign(client, election, second, geo["pu_a"]).json()["code"]
        == "polling_unit_fully_assigned"
    )
    settings.VTRS_MAX_AGENTS_PER_POLLING_UNIT = 2  # PB-06 allows two agents per unit
    assert _assign(client, election, second, geo["pu_a"]).status_code == 201


def test_no_deployment_after_polls_close(admin, client, make_member, geo):
    election = _election(admin.organization, geo, status="CLOSED")
    agent = make_member(Role.PU_AGENT, scope_ids=[geo["pu_a"].id], organization=admin.organization)
    assert _assign(client, election, agent, geo["pu_a"]).json()["code"] == "election_not_assignable"


def test_revocation(admin, client, client_as, make_member, geo):
    election = _election(admin.organization, geo)
    agent = make_member(Role.PU_AGENT, scope_ids=[geo["pu_a"].id], organization=admin.organization)
    assignment = _assign(client, election, agent, geo["pu_a"]).json()
    revoked = client.post(
        f"/api/v1/assignments/{assignment['id']}/revoke", HTTP_IDEMPOTENCY_KEY="revoke"
    )
    assert revoked.json()["status"] == "REVOKED"
    assert client_as(agent).get("/api/v1/me/assignments").json() == []
    # A revoked assignment frees the slot for a re-deployment.
    assert _assign(client, election, agent, geo["pu_a"]).status_code == 201


def test_listing_filters(admin, client, make_member, geo):
    election = _election(admin.organization, geo)
    org = admin.organization
    a = make_member(Role.PU_AGENT, scope_ids=[geo["pu_a"].id], organization=org)
    b = make_member(Role.PU_AGENT, scope_ids=[geo["pu_b"].id], organization=org)
    _assign(client, election, a, geo["pu_a"])
    _assign(client, election, b, geo["pu_b"])
    rows = client.get("/api/v1/assignments", {"polling_unit": str(geo["pu_b"].id)}).json()[
        "results"
    ]
    assert [r["agent_id"] for r in rows] == [str(b.user.id)]
    bad = client.get("/api/v1/assignments", {"ward": str(Ward.objects.first().id)})
    assert bad.json()["code"] == "unknown_query_parameter"


def test_active_assignment_check_for_submission(admin, client, make_member, geo):
    """The check result submission (M3) will use: deployed agent, right PU, right election."""
    election = _election(admin.organization, geo)
    agent = make_member(
        Role.PU_AGENT, scope_ids=[geo["pu_a"].id, geo["pu_b"].id], organization=admin.organization
    )
    _assign(client, election, agent, geo["pu_a"])
    actor = Actor(
        agent.user.id,
        admin.organization.id,
        Role.PU_AGENT,
        Scope(ScopeKind.PU, frozenset({geo["pu_a"].id, geo["pu_b"].id})),
    )
    set_tenant(admin.organization.id)
    assert active_assignment(actor, election_id=election.id, polling_unit_id=geo["pu_a"].id)
    assert not active_assignment(actor, election_id=election.id, polling_unit_id=geo["pu_b"].id)
