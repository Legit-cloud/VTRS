"""Authorization matrix (spec sections 8 and 20; AC-04, AC-14, DD-03).

Every protected endpoint x every role x four targets: in scope, a sibling ward in the same LGA,
a ward in another LGA, and another organization. Expected outcome:
  - the role lacks the permission          -> 403
  - the target belongs to another tenant   -> 404 (never 403: existence is not revealed)
  - otherwise                              -> success
`test_every_protected_route_is_in_the_matrix` fails when a new endpoint is added without a row.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from apps.accounts.models import Device, Invitation
from apps.core.domain.actor import ScopeKind
from apps.core.domain.permissions import Perm, Role, effective_permissions
from apps.core.ids import uuid7
from apps.core.rls import system_context
from apps.geography.domain.synthetic import synthetic_master_data
from apps.geography.models import Lga, PollingUnit, Ward
from apps.geography.services import import_master_data

pytestmark = pytest.mark.django_db

RELATIONS = ("in_scope", "sibling_ward", "other_lga", "other_org")


@dataclass
class World:
    org: Any
    other_org: Any
    # ward per relation, from the point of view of the scoped actors (LGA A / ward A1)
    wards: dict[str, Ward]
    lga_a: Lga


@pytest.fixture
def world(make_org) -> World:
    import_master_data(synthetic_master_data(lgas=2, wards=4, polling_units=8, seed=3))
    lga_a, lga_b = Lga.objects.order_by("inec_code")
    a1, a2 = Ward.objects.filter(lga=lga_a).order_by("inec_code")
    b1 = Ward.objects.filter(lga=lga_b).order_by("inec_code").first()
    return World(
        org=make_org("Our Party"),
        other_org=make_org("Their Party"),
        wards={"in_scope": a1, "sibling_ward": a2, "other_lga": b1, "other_org": a1},
        lga_a=lga_a,
    )


def _actor(world: World, make_member, role: Role):
    a1 = world.wards["in_scope"]
    scope = {
        Role.PARTY_ADMIN: [],
        Role.LGA_OFFICER: [world.lga_a.id],
        Role.WARD_OFFICER: [a1.id],
        Role.PU_AGENT: [PollingUnit.objects.filter(ward=a1).first().id],
    }[role]
    return make_member(role, scope_ids=scope, organization=world.org)


# --- Targets: objects placed in a given relation to the actor ------------------------------


def _target_member(world, make_member, relation):
    org = world.other_org if relation == "other_org" else world.org
    return make_member(Role.WARD_OFFICER, scope_ids=[world.wards[relation].id], organization=org)


def _target_invitation(world, make_member, relation):
    member = _target_member(world, make_member, relation)
    with system_context():
        return Invitation.objects.create(
            organization=member.organization,
            role=Role.WARD_OFFICER,
            scope_type=ScopeKind.WARD,
            scope_ids=[world.wards[relation].id],
            email="invitee@example.org",
            token_hash=uuid7().hex * 2,
            expires_at="2999-01-01T00:00:00Z",
            created_by_id=member.user.id,
        )


def _target_device(world, make_member, relation):
    org = world.other_org if relation == "other_org" else world.org
    pu = PollingUnit.objects.filter(ward=world.wards[relation]).first()
    agent = make_member(Role.PU_AGENT, scope_ids=[pu.id], organization=org)
    return Device.objects.create(user=agent.user, platform="ANDROID", app_version="1.0.0")


@dataclass(frozen=True)
class Endpoint:
    route: str
    method: str
    perm: Perm | None  # None: any authenticated user
    target: Callable | None = None
    kwargs: Callable[[Any], dict] = lambda t: {}
    body: Callable[[Any, World], dict] = lambda t, w: {}


ENDPOINTS = [
    Endpoint("me", "get", None),
    Endpoint("geography-lgas", "get", Perm.GEOGRAPHY_VIEW),
    Endpoint("geography-wards", "get", Perm.GEOGRAPHY_VIEW),
    Endpoint("geography-polling-units", "get", Perm.GEOGRAPHY_VIEW),
    Endpoint("users", "get", Perm.USERS_MANAGE),
    Endpoint("invitations", "get", Perm.USERS_MANAGE),
    Endpoint(
        "invitations",
        "post",
        Perm.USERS_MANAGE,
        body=lambda t, w: {
            "role": "WARD_OFFICER",
            "scope_ids": [str(w.wards["in_scope"].id)],
            "email": f"new-{uuid7().hex[:8]}@example.org",
        },
    ),
    Endpoint(
        "user-detail",
        "get",
        Perm.USERS_MANAGE,
        _target_member,
        kwargs=lambda t: {"user_id": t.user.id},
    ),
    Endpoint(
        "user-deactivate",
        "post",
        Perm.USERS_MANAGE,
        _target_member,
        kwargs=lambda t: {"user_id": t.user.id},
    ),
    Endpoint(
        "user-membership",
        "put",
        Perm.USERS_MANAGE,
        _target_member,
        kwargs=lambda t: {"user_id": t.user.id},
        body=lambda t, w: {
            "role": "WARD_OFFICER",
            "scope_ids": [str(i) for i in t.membership.scope_ids],
        },
    ),
    Endpoint(
        "user-device-revoke",
        "post",
        Perm.USERS_MANAGE,
        _target_device,
        kwargs=lambda t: {"user_id": t.user_id, "device_id": t.id},
    ),
    Endpoint(
        "invitation-revoke",
        "post",
        Perm.USERS_MANAGE,
        _target_invitation,
        kwargs=lambda t: {"invitation_id": t.id},
    ),
]

# Self-service routes that act only on the caller's own session; covered by their own tests.
SELF_SERVICE = {"auth-logout", "auth-totp-setup", "auth-totp-confirm", "auth-step-up"}


def _expected(endpoint: Endpoint, role: Role, relation: str) -> int:
    if endpoint.perm is not None and endpoint.perm not in effective_permissions(role):
        return 403
    if relation == "other_org":
        return 404
    return 201 if (endpoint.method == "post" and endpoint.target is None) else 200


CASES = [
    pytest.param(e, role, rel, id=f"{e.method}:{e.route}:{role.value}:{rel}")
    for e in ENDPOINTS
    for role in Role
    for rel in (RELATIONS if e.target else ("collection",))
]


@pytest.mark.parametrize(("endpoint", "role", "relation"), CASES)
def test_matrix(world, make_member, client_as, endpoint, role, relation):
    actor = _actor(world, make_member, role)
    target = endpoint.target(world, make_member, relation) if endpoint.target else None
    url = reverse(endpoint.route, kwargs=endpoint.kwargs(target))
    client = client_as(actor)
    call = getattr(client, endpoint.method)
    if endpoint.method == "get":
        response = call(url)
    else:
        response = call(
            url, endpoint.body(target, world), format="json", HTTP_IDEMPOTENCY_KEY=str(uuid7())
        )
    expected = _expected(endpoint, role, relation)
    assert response.status_code == expected, response.json()


def test_collections_never_leak_other_tenants(world, make_member, client_as):
    admin = _actor(world, make_member, Role.PARTY_ADMIN)
    theirs = _target_member(world, make_member, "other_org")
    _target_invitation(world, make_member, "other_org")
    client = client_as(admin)
    users = {r["user_id"] for r in client.get(reverse("users")).json()["results"]}
    assert str(theirs.user.id) not in users
    assert client.get(reverse("invitations")).json()["results"] == []


def _protected_routes(patterns, prefix=""):
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            yield from _protected_routes(pattern.url_patterns)
        elif isinstance(pattern, URLPattern):
            view = getattr(pattern.callback, "cls", None)
            if view is not None and getattr(view, "required_permission", None):
                yield pattern.name


def test_every_protected_route_is_in_the_matrix():
    covered = {e.route for e in ENDPOINTS} | SELF_SERVICE
    missing = set(_protected_routes(get_resolver().url_patterns)) - covered
    assert not missing, f"Add these routes to the authorization matrix: {sorted(missing)}"
