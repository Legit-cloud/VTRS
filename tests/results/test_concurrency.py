"""M3 exit gate: 100 parallel replays of one submission id create exactly one row; two agents
racing one polling unit get one pu_result and two versions (real connections, real commits)."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import connection, transaction

from apps.accounts.models import Membership, Session, User, UserStatus
from apps.accounts.services.sessions import start_session
from apps.anomalies.models import AnomalyFlag
from apps.assignments.models import AgentAssignment
from apps.core.crypto import blind_index
from apps.core.domain.actor import Actor, Scope, ScopeKind
from apps.core.domain.permissions import Role
from apps.elections.models import Election
from apps.geography.models import PollingUnit, State
from apps.organizations.models import Organization
from apps.results import services
from apps.results.api.serializers import SubmissionSerializer
from apps.results.models import PuResult, ResultVersion

from ..factories import election_type, load_reference_data, make_ballot
from .conftest import seal

pytestmark = pytest.mark.django_db(transaction=True)


def _world():
    with transaction.atomic():
        load_reference_data(lgas=1, wards=1, polling_units=1, seed=1)
    pu = PollingUnit.objects.get()
    org = Organization.objects.create(name="Race Party", status="ACTIVE")
    election = Election.objects.create(
        organization=org,
        name="Race",
        election_type=election_type(),
        state=State.objects.get(),
        election_date="2027-03-11",
        status="LIVE",
        created_by_id=org.id,
    )
    ballot = make_ballot(org, election, ("AAA", "BBB"), own=None)
    return org, election, ballot.contest, ballot.candidates, pu


def _agent(org, election, pu, n):
    email = f"agent{n}@race.example"
    user = User.objects.create_user(
        password="x" * 20,
        email=email,
        email_index=blind_index("email", email),
        status=UserStatus.ACTIVE,
    )
    membership = Membership.objects.create(
        user=user, organization=org, role=Role.PU_AGENT, scope_type=ScopeKind.PU, scope_ids=[pu.id]
    )
    AgentAssignment.objects.create(
        organization=org,
        election=election,
        agent=user,
        polling_unit=pu,
        ward_id=pu.ward_id,
        lga_id=pu.lga_id,
        assigned_by_id=user.id,
    )
    with transaction.atomic():
        start_session(user=user, membership=membership, mfa_at=None, ip=None)
    session = Session.objects.get(user=user)
    actor = Actor(
        user.id,
        org.id,
        Role.PU_AGENT,
        Scope(ScopeKind.PU, frozenset({pu.id})),
        session_id=session.id,
    )
    return actor


def _item(election, candidates, pu, **extra):
    from django.utils import timezone

    from apps.core.ids import uuid7

    item = {
        "version_id": str(uuid7()),
        "election_id": str(election.id),
        "polling_unit_id": str(pu.id),
        "config_version": 1,
        "parent_version_id": None,
        "totals": {"accredited": 210, "rejected": 5, "total_cast": 205},
        "votes": [
            {"candidate_id": str(c.id), "votes": v}
            for c, v in zip(candidates, (120, 80), strict=True)
        ],
        "device_captured_at": timezone.now().isoformat(),
        "gps": {
            "lat": float(pu.latitude or 7.39),
            "lng": float(pu.longitude or 3.91),
            "accuracy_m": 10,
        },
        **extra,
    }
    return seal(item)


def _submit(actor, raw):
    try:
        serializer = SubmissionSerializer(data=raw)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            return services.submit(actor, serializer.validated_data, raw)
    finally:
        connection.close()


def test_one_hundred_parallel_replays_create_one_version():
    org, election, _contest, candidates, pu = _world()
    actor = _agent(org, election, pu, 1)
    item = _item(election, candidates, pu)

    start = threading.Barrier(30)

    def attempt(_):
        try:
            start.wait(timeout=10)
        except threading.BrokenBarrierError:
            pass
        return _submit(actor, item)

    with ThreadPoolExecutor(max_workers=30) as pool:
        outcomes = list(pool.map(attempt, range(100)))

    assert all(o["status"] == "ACCEPTED" for o in outcomes), {o.get("code") for o in outcomes}
    assert sum(not o["replayed"] for o in outcomes) == 1
    assert ResultVersion.objects.filter(id=item["version_id"]).count() == 1
    assert PuResult.objects.get().version_count == 1


def test_two_agents_racing_one_polling_unit():
    org, election, _contest, candidates, pu = _world()
    actor_a, actor_b = (_agent(org, election, pu, n) for n in (1, 2))
    items = [
        (actor_a, _item(election, candidates, pu)),
        (actor_b, _item(election, candidates, pu)),
    ]
    barrier = threading.Barrier(2)

    def race(pair):
        barrier.wait(timeout=10)
        return _submit(*pair)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(race, items))

    assert PuResult.objects.count() == 1
    assert sorted(ResultVersion.objects.values_list("version_no", flat=True)) == [1, 2]
    # Whoever lost the race is a second source that also didn't build on the winner's version.
    assert sorted(tuple(o["flags"]) for o in outcomes) == [(), ("DUPLICATE_SOURCE", "VERSION_FORK")]
    assert AnomalyFlag.objects.filter(rule_code="DUPLICATE_SOURCE").count() == 1


def test_racing_corrections_get_distinct_version_numbers():
    """Once a result exists, only the row lock keeps concurrent versions from colliding."""
    org, election, _contest, candidates, pu = _world()
    actor_a, actor_b = (_agent(org, election, pu, n) for n in (1, 2))
    first = _item(election, candidates, pu)
    assert _submit(actor_a, first)["status"] == "ACCEPTED"

    pairs = [
        (actor_a, _item(election, candidates, pu, parent_version_id=first["version_id"])),
        (actor_b, _item(election, candidates, pu, parent_version_id=first["version_id"])),
    ]
    barrier = threading.Barrier(2)

    def race(pair):
        barrier.wait(timeout=10)
        return _submit(*pair)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(race, pairs))

    assert all(o["status"] != "FAILED" for o in outcomes), outcomes
    assert sorted(ResultVersion.objects.values_list("version_no", flat=True)) == [1, 2, 3]
    assert PuResult.objects.get().version_count == 3
