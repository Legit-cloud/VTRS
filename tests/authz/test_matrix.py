"""Authorization matrix (spec sections 8 and 20; AC-04, AC-14, DD-03).

Every protected endpoint x every role x four targets: in scope, a sibling ward in the same LGA,
a ward in another LGA, and another organization. Expected outcome:
  - the role lacks the permission          -> 403
  - the target belongs to another tenant   -> 404 (never 403: existence is not revealed)
  - otherwise                              -> the endpoint's success status
`test_every_protected_route_is_in_the_matrix` fails when a protected route+method has no row.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django.utils import timezone

from apps.accounts.models import Device, Invitation
from apps.assignments.models import AgentAssignment
from apps.core.api.permissions import required_permission_for
from apps.core.authz import AUTHENTICATED
from apps.core.domain.actor import ScopeKind
from apps.core.domain.permissions import Perm, Role, effective_permissions
from apps.core.ids import uuid7
from apps.core.rls import system_context
from apps.elections.models import Candidate, Contest, Election
from apps.evidence.models import EvidenceFile
from apps.geography.domain.synthetic import synthetic_master_data
from apps.geography.models import Lga, PollingUnit, State, Ward
from apps.geography.services import import_master_data
from apps.results.models import PuResult, ResultVersion

pytestmark = pytest.mark.django_db

RELATIONS = ("in_scope", "sibling_ward", "other_lga", "other_org")


@dataclass
class World:
    org: Any
    other_org: Any
    state: State
    lga_a: Lga
    # ward per relation, from the point of view of the scoped actors (LGA A / ward A1)
    wards: dict[str, Ward]
    make_member: Callable[..., Any]

    def org_for(self, relation: str) -> Any:
        return self.other_org if relation == "other_org" else self.org

    def pu(self, relation: str) -> PollingUnit:
        return PollingUnit.objects.filter(ward=self.wards[relation]).order_by("inec_code").first()


@pytest.fixture
def world(make_org, make_member) -> World:
    import_master_data(synthetic_master_data(lgas=2, wards=4, polling_units=8, seed=3))
    lga_a, lga_b = Lga.objects.order_by("inec_code")
    a1, a2 = Ward.objects.filter(lga=lga_a).order_by("inec_code")
    b1 = Ward.objects.filter(lga=lga_b).order_by("inec_code").first()
    return World(
        org=make_org("Our Party"),
        other_org=make_org("Their Party"),
        state=State.objects.get(),
        lga_a=lga_a,
        wards={"in_scope": a1, "sibling_ward": a2, "other_lga": b1, "other_org": a1},
        make_member=make_member,
    )


def _actor(w: World, role: Role):
    scope = {
        Role.PARTY_ADMIN: [],
        Role.LGA_OFFICER: [w.lga_a.id],
        Role.WARD_OFFICER: [w.wards["in_scope"].id],
        Role.PU_AGENT: [w.pu("in_scope").id],
    }[role]
    return w.make_member(role, scope_ids=scope, organization=w.org)


# --- Targets: objects placed in a given relation to the actor ------------------------------


def _member(w: World, relation: str):
    return w.make_member(
        Role.WARD_OFFICER, scope_ids=[w.wards[relation].id], organization=w.org_for(relation)
    )


def _invitation(w: World, relation: str):
    member = _member(w, relation)
    with system_context():
        return Invitation.objects.create(
            organization=member.organization,
            role=Role.WARD_OFFICER,
            scope_type=ScopeKind.WARD,
            scope_ids=[w.wards[relation].id],
            email="invitee@example.org",
            token_hash=uuid7().hex * 2,
            expires_at="2999-01-01T00:00:00Z",
            created_by_id=member.user.id,
        )


def _device(w: World, relation: str):
    agent = w.make_member(
        Role.PU_AGENT, scope_ids=[w.pu(relation).id], organization=w.org_for(relation)
    )
    return Device.objects.create(user=agent.user, platform="ANDROID", app_version="1.0.0")


def _election(w: World, relation: str, status: str = "DRAFT") -> Election:
    with system_context():
        election = Election.objects.create(
            organization=w.org_for(relation),
            name=f"Election {uuid7().hex[-12:]}",
            state=w.state,
            election_date="2027-03-01",
            status=status,
            created_by_id=uuid7(),
        )
        contest = Contest.objects.create(
            organization=w.org_for(relation),
            election=election,
            office="GOVERNORSHIP",
            title="Governor",
            jurisdiction_level="STATE",
            jurisdiction_ids=[w.state.id],
        )
        for order, acronym in ((1, "AAA"), (2, "BBB")):
            Candidate.objects.create(
                organization=w.org_for(relation),
                contest=contest,
                name=f"Candidate {acronym}",
                party_name=f"Party {acronym}",
                party_acronym=acronym,
                ballot_order=order,
                config_version=1,
            )
    return election


def _configured_election(w: World, relation: str) -> Election:
    return _election(w, relation, status="CONFIGURED")


def _contest(w: World, relation: str) -> Contest:
    election = _election(w, relation)
    with system_context():
        return election.contests.get()


def _candidate(w: World, relation: str) -> Candidate:
    contest = _contest(w, relation)
    with system_context():
        return Candidate.objects.filter(contest=contest).order_by("ballot_order").first()


def _assignment(w: World, relation: str) -> AgentAssignment:
    pu = w.pu(relation)
    agent = w.make_member(Role.PU_AGENT, scope_ids=[pu.id], organization=w.org_for(relation))
    election = _election(w, relation)
    with system_context():
        return AgentAssignment.objects.create(
            organization=w.org_for(relation),
            election=election,
            agent=agent.user,
            polling_unit=pu,
            ward=pu.ward,
            lga=pu.lga,
            assigned_by_id=uuid7(),
        )


def _new_assignment_body(t: Any, w: World) -> dict:
    pu = w.pu("in_scope")
    agent = w.make_member(Role.PU_AGENT, scope_ids=[pu.id], organization=w.org)
    return {
        "election_id": str(_election(w, "in_scope").id),
        "agent_id": str(agent.user.id),
        "polling_unit_id": str(pu.id),
    }


def _if_match(t: Any) -> dict:
    return {"HTTP_IF_MATCH": f'"{t.row_version}"'}


def _evidence(w: World, relation: str) -> EvidenceFile:
    """A verified photo uploaded by *another* agent at the relation's polling unit."""
    pu = w.pu(relation)
    org = w.org_for(relation)
    uploader = w.make_member(Role.PU_AGENT, scope_ids=[pu.id], organization=org)
    election = _election(w, relation)
    with system_context():
        contest = election.contests.get()
        pu_result = PuResult.objects.create(
            organization=org,
            election=election,
            contest=contest,
            polling_unit=pu,
            ward=pu.ward,
            lga=pu.lga,
            state=w.state,
        )
        version = ResultVersion.objects.create(
            id=uuid7(),
            organization=org,
            pu_result=pu_result,
            contest=contest,
            polling_unit=pu,
            ward=pu.ward,
            lga=pu.lga,
            version_no=1,
            valid=10,
            device_captured_at=timezone.now(),
            server_received_at=timezone.now(),
            submitted_by=uploader.user,
            app_version="1.0.0",
            config_version=1,
            payload_hash="0" * 64,
            state="SUBMITTED",
        )
        evidence_id = uuid7()
        return EvidenceFile.objects.create(
            id=evidence_id,
            organization=org,
            result_version=version,
            polling_unit=pu,
            ward=pu.ward,
            lga=pu.lga,
            uploaded_by=uploader.user,
            kind="EC8A",
            object_key=f"org/{org.id}/{evidence_id}.jpg",
            size=10,
            mime="image/jpeg",
            sha256_client="0" * 64,
            status="VERIFIED",
        )


def _admin_in_org(role: Role, relation: str) -> bool:
    return role is Role.PARTY_ADMIN and relation != "other_org"


def _never(role: Role, relation: str) -> bool:
    return False


@dataclass(frozen=True)
class Endpoint:
    route: str
    method: str
    perm: Perm | str
    target: Callable[[World, str], Any] | None = None
    kwargs: Callable[[Any], dict] = lambda t: {}
    body: Callable[[Any, World], dict] = lambda t, w: {}
    headers: Callable[[Any], dict] = lambda t: {}
    query: dict = None  # type: ignore[assignment]
    ok: int = 200
    # For endpoints with their own visibility rules (e.g. agents see only their own uploads):
    # (role, relation) -> visible. Roles that hold the permission but can't see get 404.
    visible: Callable[[Role, str], bool] | None = None


_user = {"kwargs": lambda t: {"user_id": t.user.id}}
_election_kw = {"kwargs": lambda t: {"election_id": t.id}}
_contest_kw = {"kwargs": lambda t: {"contest_id": t.id}}
_candidate_kw = {"kwargs": lambda t: {"candidate_id": t.id}}

ENDPOINTS = [
    # accounts
    Endpoint("me", "get", AUTHENTICATED),
    Endpoint("users", "get", Perm.USERS_MANAGE),
    Endpoint("invitations", "get", Perm.USERS_MANAGE),
    Endpoint(
        "invitations",
        "post",
        Perm.USERS_MANAGE,
        body=lambda t, w: {
            "role": "WARD_OFFICER",
            "scope_ids": [str(w.wards["in_scope"].id)],
            "email": f"new-{uuid7().hex[-12:]}@example.org",
        },
        ok=201,
    ),
    Endpoint("user-detail", "get", Perm.USERS_MANAGE, _member, **_user),
    Endpoint("user-deactivate", "post", Perm.USERS_MANAGE, _member, **_user),
    Endpoint(
        "user-membership",
        "put",
        Perm.USERS_MANAGE,
        _member,
        body=lambda t, w: {
            "role": "WARD_OFFICER",
            "scope_ids": [str(i) for i in t.membership.scope_ids],
        },
        **_user,
    ),
    Endpoint(
        "user-device-revoke",
        "post",
        Perm.USERS_MANAGE,
        _device,
        kwargs=lambda t: {"user_id": t.user_id, "device_id": t.id},
    ),
    Endpoint(
        "invitation-revoke",
        "post",
        Perm.USERS_MANAGE,
        _invitation,
        kwargs=lambda t: {"invitation_id": t.id},
    ),
    # geography
    Endpoint("geography-lgas", "get", Perm.GEOGRAPHY_VIEW),
    Endpoint("geography-wards", "get", Perm.GEOGRAPHY_VIEW),
    Endpoint("geography-polling-units", "get", Perm.GEOGRAPHY_VIEW),
    # elections
    Endpoint("elections", "get", AUTHENTICATED),
    Endpoint(
        "elections",
        "post",
        Perm.ELECTIONS_CONFIGURE,
        body=lambda t, w: {
            "name": f"New {uuid7().hex[-12:]}",
            "state_id": str(w.state.id),
            "election_date": "2027-03-01",
        },
        ok=201,
    ),
    Endpoint("election-detail", "get", AUTHENTICATED, _election, **_election_kw),
    Endpoint(
        "election-detail",
        "patch",
        Perm.ELECTIONS_CONFIGURE,
        _election,
        body=lambda t, w: {"name": f"Renamed {uuid7().hex[-12:]}"},
        headers=_if_match,
        **_election_kw,
    ),
    Endpoint(
        "election-transition",
        "post",
        Perm.ELECTIONS_CONFIGURE,
        _election,
        body=lambda t, w: {"to": "CONFIGURED"},
        **_election_kw,
    ),
    Endpoint(
        "election-lock", "post", Perm.ELECTIONS_CONFIGURE, _configured_election, **_election_kw
    ),
    Endpoint("election-contests", "get", AUTHENTICATED, _election, **_election_kw),
    Endpoint(
        "election-contests",
        "post",
        Perm.ELECTIONS_CONFIGURE,
        _election,
        body=lambda t, w: {
            "office": "STATE_ASSEMBLY",
            "title": "Assembly",
            "jurisdiction_level": "LGA",
            "jurisdiction_ids": [str(w.lga_a.id)],
        },
        ok=201,
        **_election_kw,
    ),
    Endpoint("contest-detail", "get", AUTHENTICATED, _contest, **_contest_kw),
    Endpoint(
        "contest-detail",
        "patch",
        Perm.ELECTIONS_CONFIGURE,
        _contest,
        body=lambda t, w: {"title": "Governor (renamed)"},
        headers=_if_match,
        **_contest_kw,
    ),
    Endpoint("contest-detail", "delete", Perm.ELECTIONS_CONFIGURE, _contest, ok=204, **_contest_kw),
    Endpoint("contest-candidates", "get", AUTHENTICATED, _contest, **_contest_kw),
    Endpoint(
        "contest-candidates",
        "post",
        Perm.CANDIDATES_MANAGE,
        _contest,
        body=lambda t, w: {
            "name": "Third",
            "party_name": "Party C",
            "party_acronym": "CCC",
            "ballot_order": 3,
        },
        ok=201,
        **_contest_kw,
    ),
    Endpoint("candidate-detail", "get", AUTHENTICATED, _candidate, **_candidate_kw),
    Endpoint(
        "candidate-detail",
        "patch",
        Perm.CANDIDATES_MANAGE,
        _candidate,
        body=lambda t, w: {"name": "Renamed Candidate"},
        headers=_if_match,
        **_candidate_kw,
    ),
    Endpoint(
        "candidate-detail", "delete", Perm.CANDIDATES_MANAGE, _candidate, ok=204, **_candidate_kw
    ),
    # assignments
    Endpoint("assignments", "get", Perm.ASSIGNMENTS_MANAGE),
    Endpoint("assignments", "post", Perm.ASSIGNMENTS_MANAGE, body=_new_assignment_body, ok=201),
    Endpoint(
        "assignment-revoke",
        "post",
        Perm.ASSIGNMENTS_MANAGE,
        _assignment,
        kwargs=lambda t: {"assignment_id": t.id},
    ),
    Endpoint("my-assignments", "get", Perm.RESULTS_SUBMIT),
    # results and evidence
    Endpoint("sync-submissions", "post", Perm.RESULTS_SUBMIT, body=lambda t, w: {"items": [{}]}),
    Endpoint("sync-status", "get", Perm.RESULTS_SUBMIT, query={"ids": str(uuid7())}),
    Endpoint(
        "evidence-uploads",
        "post",
        Perm.RESULTS_SUBMIT,
        _evidence,
        body=lambda t, w: {
            "version_id": str(t.result_version_id),
            "evidence_id": str(uuid7()),
            "kind": "EC8A",
            "size": 10,
            "mime": "image/jpeg",
            "sha256": "0" * 64,
        },
        visible=_never,  # someone else's submission
    ),
    Endpoint(
        "evidence-complete",
        "post",
        Perm.RESULTS_SUBMIT,
        _evidence,
        kwargs=lambda t: {"evidence_id": t.id},
        visible=_never,  # someone else's upload
    ),
    Endpoint(
        "evidence-download-url",
        "post",
        Perm.EVIDENCE_VIEW,
        _evidence,
        kwargs=lambda t: {"evidence_id": t.id},
        visible=_admin_in_org,  # agents hold evidence.view only for their own uploads
    ),
]

# Self-service routes that act only on the caller's own session; covered by their own tests.
SELF_SERVICE = {
    ("auth-logout", "POST"),
    ("auth-totp-setup", "POST"),
    ("auth-totp-confirm", "POST"),
    ("auth-step-up", "POST"),
}


def _has(role: Role, perm: Perm | str) -> bool:
    return perm == AUTHENTICATED or Perm(perm) in effective_permissions(role)


def _expected(endpoint: Endpoint, role: Role, relation: str) -> int:
    if not _has(role, endpoint.perm):
        return 403
    if endpoint.visible is not None:
        return endpoint.ok if endpoint.visible(role, relation) else 404
    if relation == "other_org":
        return 404
    return endpoint.ok


CASES = [
    pytest.param(e, role, rel, id=f"{e.method}:{e.route}:{role.value}:{rel}")
    for e in ENDPOINTS
    for role in Role
    for rel in (RELATIONS if e.target else ("collection",))
]


@pytest.mark.parametrize(("endpoint", "role", "relation"), CASES)
def test_matrix(world, client_as, endpoint, role, relation):
    actor = _actor(world, role)
    target = endpoint.target(world, relation) if endpoint.target else None
    url = reverse(endpoint.route, kwargs=endpoint.kwargs(target))
    client = client_as(actor)
    call = getattr(client, endpoint.method)
    headers = endpoint.headers(target) if target is not None else {}
    if endpoint.method in {"get", "delete"}:
        response = call(url, endpoint.query or {}, **headers)
    else:
        body = endpoint.body(target, world) if _has(role, endpoint.perm) else {}
        response = call(url, body, format="json", HTTP_IDEMPOTENCY_KEY=str(uuid7()), **headers)
    expected = _expected(endpoint, role, relation)
    detail = response.json() if response.content else None
    assert response.status_code == expected, detail


def test_collections_never_leak_other_tenants(world, client_as):
    admin = _actor(world, Role.PARTY_ADMIN)
    theirs = _member(world, "other_org")
    _invitation(world, "other_org")
    _election(world, "other_org")
    _assignment(world, "other_org")
    client = client_as(admin)
    users = {r["user_id"] for r in client.get(reverse("users")).json()["results"]}
    assert str(theirs.user.id) not in users
    assert client.get(reverse("invitations")).json()["results"] == []
    assert client.get(reverse("elections")).json()["results"] == []
    assert client.get(reverse("assignments")).json()["results"] == []


def _protected(patterns):
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            yield from _protected(pattern.url_patterns)
        elif isinstance(pattern, URLPattern):
            view = getattr(pattern.callback, "cls", None)
            if view is None or getattr(view, "public", False):
                continue
            for method in view.http_method_names:
                if method in {"options", "head"} or not hasattr(view, method):
                    continue
                if required_permission_for(view, method.upper()):
                    yield pattern.name, method.upper()


def test_every_protected_route_is_in_the_matrix():
    covered = {(e.route, e.method.upper()) for e in ENDPOINTS} | SELF_SERVICE
    missing = set(_protected(get_resolver().url_patterns)) - covered
    assert not missing, f"Add these routes to the authorization matrix: {sorted(missing)}"


def test_matrix_permissions_match_the_views():
    """The matrix's expectations must agree with what each view actually declares."""
    resolver = get_resolver()
    for endpoint in ENDPOINTS:
        match = resolver.resolve(reverse(endpoint.route, kwargs=_dummy_kwargs(endpoint)))
        declared = required_permission_for(match.func.cls, endpoint.method.upper())
        assert declared == endpoint.perm, (endpoint.route, endpoint.method, declared)


def _dummy_kwargs(endpoint: Endpoint) -> dict:
    pattern_kwargs = {
        "user_id",
        "device_id",
        "invitation_id",
        "election_id",
        "contest_id",
        "candidate_id",
        "assignment_id",
        "evidence_id",
    }
    route = next(
        p for p in _flatten(get_resolver().url_patterns) if p.name == endpoint.route
    ).pattern.converters
    return {name: uuid7() for name in route if name in pattern_kwargs}


def _flatten(patterns):
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            yield from _flatten(pattern.url_patterns)
        else:
            yield pattern
