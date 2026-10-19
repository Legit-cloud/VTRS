"""AC-03: admins deploy agents to polling units. AC-04 / FR-6.2.5: the agent sees only their
own assignments, and the result form for each, before capture."""

import pytest

from apps.assignments.selectors import active_assignment
from apps.audit.models import AuditEvent
from apps.core.domain.actor import Actor, Scope, ScopeKind
from apps.core.domain.permissions import Role
from apps.core.rls import set_tenant, system_context
from apps.elections.models import Election
from apps.geography.models import Constituency, Lga, PollingUnit, State, Ward

from ..factories import election_type, load_reference_data, make_ballot, make_parties

pytestmark = pytest.mark.django_db
KEY = iter(range(1, 10_000))


@pytest.fixture
def geo():
    load_reference_data(lgas=2, wards=4, polling_units=8, seed=8)
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
    """An LGA chairmanship: one race per LGA, each with its own candidates."""
    with system_context():
        election = Election.objects.create(
            organization=org,
            name=f"Election {next(KEY)}",
            election_type=election_type("LGA_CHAIRMANSHIP"),
            state=geo["state"],
            election_date="2027-03-11",
            status=status,
            created_by_id=org.id,
        )
    parties = make_parties(org, (f"B{next(KEY)}", f"A{next(KEY)}"))
    for lga in (geo["lga_a"], geo["lga_b"]):
        make_ballot(
            org,
            election,
            constituency=Constituency.objects.get(kind="LGA", code=lga.inec_code),
            parties=parties,
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
    assert in_a["result"] is None
    # Each unit's form lists its own constituency's contestants, in the election's party order.
    agent_client = client_as(agent)
    forms = {
        code: agent_client.get(
            f"/api/v1/elections/{election.id}/polling-units/{row['polling_unit']['id']}/form"
        ).json()
        for code, row in by_pu.items()
    }
    form_a = forms[geo["pu_a"].inec_code]
    assert form_a["constituency"]["name"] == geo["lga_a"].name
    assert [p["ballot_order"] for p in form_a["parties"]] == [1, 2]
    assert forms[geo["pu_b"].inec_code]["constituency"]["name"] == geo["lga_b"].name


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


def test_up_to_three_agents_per_polling_unit(admin, client, make_member, geo):
    """PB-06: at most three agents per polling unit per election."""
    election = _election(admin.organization, geo)
    org = admin.organization
    agents = [
        make_member(Role.PU_AGENT, scope_ids=[geo["pu_a"].id], organization=org) for _ in range(4)
    ]
    for agent in agents[:3]:
        assert _assign(client, election, agent, geo["pu_a"]).status_code == 201
    assert _assign(client, election, agents[0], geo["pu_a"]).json()["code"] == "already_assigned"
    fourth = _assign(client, election, agents[3], geo["pu_a"])
    assert fourth.status_code == 409
    assert fourth.json()["code"] == "polling_unit_fully_assigned"
    # The cap is per election: the same unit can be staffed again for another election.
    other = _election(org, geo)
    assert _assign(client, other, agents[3], geo["pu_a"]).status_code == 201


def test_cap_holds_after_a_revocation(admin, client, make_member, geo):
    election = _election(admin.organization, geo)
    org = admin.organization
    agents = [
        make_member(Role.PU_AGENT, scope_ids=[geo["pu_a"].id], organization=org) for _ in range(4)
    ]
    created = [_assign(client, election, a, geo["pu_a"]).json() for a in agents[:3]]
    client.post(f"/api/v1/assignments/{created[0]['id']}/revoke", HTTP_IDEMPOTENCY_KEY="rv")
    assert _assign(client, election, agents[3], geo["pu_a"]).status_code == 201
    assert (
        _assign(client, election, agents[0], geo["pu_a"]).json()["code"]
        == "polling_unit_fully_assigned"
    )


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


def test_deactivating_an_agent_frees_their_polling_unit(
    admin, client, client_as, make_member, geo, settings
):
    """A deactivated agent cannot report, so they must stop occupying the unit's capacity."""
    settings.VTRS_MAX_AGENTS_PER_POLLING_UNIT = 1
    election = _election(admin.organization, geo, status="LIVE")
    org = admin.organization
    leaving = make_member(Role.PU_AGENT, scope_ids=[geo["pu_a"].id], organization=org)
    arriving = make_member(Role.PU_AGENT, scope_ids=[geo["pu_a"].id], organization=org)
    assert _assign(client, election, leaving, geo["pu_a"]).status_code == 201
    # The unit is full: the replacement cannot be placed yet.
    assert _assign(client, election, arriving, geo["pu_a"]).status_code == 409

    done = client.post(
        f"/api/v1/users/{leaving.user.id}/deactivate", {}, format="json", HTTP_IDEMPOTENCY_KEY="d-1"
    )
    assert done.status_code == 200
    active = client.get("/api/v1/assignments", {"status": "ACTIVE"}).json()["results"]
    assert active == []
    ended = AuditEvent.objects.get(action="assignment.revoked")
    assert ended.diff["reason"] == "agent_deactivated"
    assert AuditEvent.objects.get(action="user.deactivated").diff["assignments_ended"] == 1

    # Now the replacement fits, and the deactivated agent can do nothing.
    assert _assign(client, election, arriving, geo["pu_a"]).status_code == 201
    assert client_as(leaving).get("/api/v1/me/assignments").status_code == 401


def test_polling_units_can_be_looked_up_by_id_and_carry_their_state(admin, client, geo):
    rows = client.get(
        "/api/v1/geography/polling-units", {"ids": f"{geo['pu_a'].id},{geo['pu_b'].id}"}
    ).json()["results"]
    assert {r["id"] for r in rows} == {str(geo["pu_a"].id), str(geo["pu_b"].id)}
    assert {r["state_id"] for r in rows} == {str(geo["state"].id)}
    bad = client.get("/api/v1/geography/polling-units", {"ids": "not-a-uuid"})
    assert bad.status_code == 400
