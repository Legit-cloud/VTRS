"""The per-polling-unit cap must hold when deployments race (real connections, real commits)."""

import threading

import pytest
from django.db import connection, transaction

from apps.accounts.models import Membership, User, UserStatus
from apps.assignments.errors import PollingUnitFullyAssigned
from apps.assignments.models import AgentAssignment
from apps.assignments.services import assign
from apps.core.crypto import blind_index
from apps.core.domain.actor import Actor, Scope, ScopeKind
from apps.core.domain.permissions import Role
from apps.elections.models import Election
from apps.geography.domain.synthetic import synthetic_master_data
from apps.geography.models import PollingUnit, State
from apps.geography.services import import_master_data
from apps.organizations.models import Organization


def _agent(org, pu, n):
    email, phone = f"race{n}@example.org", f"+234805{n:07d}"
    user = User.objects.create_user(
        password="correct-horse-battery-staple",
        email=email,
        email_index=blind_index("email", email),
        phone=phone,
        phone_index=blind_index("phone", phone),
        status=UserStatus.ACTIVE,
    )
    Membership.objects.create(
        user=user, organization=org, role=Role.PU_AGENT, scope_type=ScopeKind.PU, scope_ids=[pu.id]
    )
    return user


@pytest.mark.django_db(transaction=True)
def test_cap_of_three_holds_under_concurrent_requests():
    with transaction.atomic():
        import_master_data(synthetic_master_data(lgas=1, wards=1, polling_units=1))
    pu = PollingUnit.objects.get()
    org = Organization.objects.create(name="Race Party", status="ACTIVE")
    admin = User.objects.create_user(
        password="x" * 20,
        email="admin@race.example",
        email_index=blind_index("email", "admin@race.example"),
        status=UserStatus.ACTIVE,
    )
    election = Election.objects.create(
        organization=org,
        name="Race",
        state=State.objects.get(),
        election_date="2027-03-11",
        status="LOCKED",
        created_by_id=admin.id,
    )
    agents = [_agent(org, pu, n) for n in range(6)]
    actor = Actor(admin.id, org.id, Role.PARTY_ADMIN, Scope(ScopeKind.ORG))

    barrier = threading.Barrier(len(agents))
    outcomes: list[str] = []
    lock = threading.Lock()

    def deploy(agent):
        try:
            barrier.wait()
            with transaction.atomic():
                assign(actor, election_id=election.id, agent_id=agent.id, polling_unit_id=pu.id)
            result = "created"
        except PollingUnitFullyAssigned:
            result = "full"
        except Exception as exc:  # surface anything unexpected in the assertion below
            result = f"error: {exc!r}"
        finally:
            connection.close()
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=deploy, args=(a,)) for a in agents]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert sorted(outcomes) == ["created"] * 3 + ["full"] * 3, outcomes
    assert AgentAssignment.objects.filter(election=election, polling_unit=pu).count() == 3
