"""A small election to aggregate: two LGAs, two wards each, two polling units per ward."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
from django.utils import timezone

from apps.accounts.models import Device
from apps.accounts.services.sessions import start_session
from apps.assignments.models import AgentAssignment
from apps.core.domain.permissions import Role
from apps.core.ids import uuid7
from apps.core.rls import system_context
from apps.elections.models import Candidate, Contest, Election
from apps.geography.domain.synthetic import synthetic_master_data
from apps.geography.models import Lga, PollingUnit, State, Ward
from apps.geography.services import import_master_data

from ..conftest import CommitClient
from ..results.conftest import Agent, seal


@dataclass
class Field:
    org: Any
    admin: Any
    election: Election
    contest: Contest
    candidates: list[Candidate]
    lgas: list[Lga]
    wards: list[Ward]
    pus: list[PollingUnit]
    agents: dict[Any, Agent]
    make_member: Callable[..., Any]
    client_as: Callable[..., CommitClient]
    capture: Any
    extra: dict = field(default_factory=dict)

    # --- geometry ---
    def pus_of(self, ward: Ward) -> list[PollingUnit]:
        return [p for p in self.pus if p.ward_id == ward.id]

    def wards_of(self, lga: Lga) -> list[Ward]:
        return [w for w in self.wards if w.lga_id == lga.id]

    # --- people ---
    def officer(self, role: Role, scope: Any) -> Any:
        return self.make_member(role, scope_ids=[scope.id], organization=self.org)

    def admin_client(self) -> CommitClient:
        return self.client_as(self.admin)

    def officer_client(self, role: Role, scope: Any) -> CommitClient:
        return self.client_as(self.officer(role, scope))

    # --- submissions ---
    def item(self, pu: PollingUnit, votes: tuple[int, int] = (120, 80), **overrides: Any) -> dict:
        agent = self.agents[pu.id]
        totals = overrides.pop(
            "totals",
            {"accredited": 400, "valid": sum(votes), "rejected": 5, "total_cast": sum(votes) + 5},
        )
        body = {
            "version_id": str(uuid7()),
            "contest_id": str(self.contest.id),
            "polling_unit_id": str(pu.id),
            "config_version": self.election.config_version,
            "parent_version_id": None,
            "totals": totals,
            "votes": [
                {"candidate_id": str(c.id), "votes": v}
                for c, v in zip(self.candidates, votes, strict=True)
            ],
            "device_captured_at": timezone.now().isoformat(),
            "gps": {
                "lat": float(pu.latitude or 7.39),
                "lng": float(pu.longitude or 3.91),
                "accuracy_m": 12.5,
            },
            "device_id": str(agent.device.id),
            "app_version": "1.0.0",
            "evidence": [],
        }
        body.update(overrides)
        return seal(body)

    def submit(self, pu: PollingUnit, votes: tuple[int, int] = (120, 80), **overrides: Any) -> dict:
        item = self.item(pu, votes, **overrides)
        response = self.agents[pu.id].client.post(
            "/api/v1/sync/submissions", {"items": [item]}, format="json"
        )
        assert response.status_code == 200, response.content
        outcome = response.json()["items"][0]
        assert outcome["status"] in {"SYNCED", "REQUIRES_REVIEW"}, outcome
        outcome["item"] = item
        return outcome


def build_field(
    make_org,
    make_member,
    client_as,
    capture,
    *,
    review_enabled: bool,
    polling_units: int = 8,
) -> Field:
    import_master_data(synthetic_master_data(lgas=2, wards=4, polling_units=polling_units, seed=5))
    lgas = list(Lga.objects.order_by("inec_code"))
    wards = list(Ward.objects.order_by("inec_code"))
    pus = list(PollingUnit.objects.order_by("inec_code"))
    for index, pu in enumerate(pus):
        PollingUnit.objects.filter(id=pu.id).update(registered_voters=500 + index)
    pus = list(PollingUnit.objects.order_by("inec_code"))
    org = make_org("Aggregation Party")
    admin = make_member(Role.PARTY_ADMIN, organization=org, mfa_enabled=True)
    with system_context():
        election = Election.objects.create(
            organization=org,
            name="Governorship",
            state=State.objects.get(),
            election_date="2027-03-11",
            status="LIVE",
            config_version=3,
            review_enabled=review_enabled,
            created_by_id=admin.user.id,
        )
        contest = Contest.objects.create(
            organization=org,
            election=election,
            office="GOVERNORSHIP",
            title="Governor",
            jurisdiction_level="STATE",
            jurisdiction_ids=[election.state_id],
        )
        candidates = [
            Candidate.objects.create(
                organization=org,
                contest=contest,
                name=f"Candidate {acr}",
                party_name=acr,
                party_acronym=acr,
                ballot_order=order,
                is_own_party=order == 1,
                config_version=1,
            )
            for order, acr in ((1, "AAA"), (2, "BBB"))
        ]

    agents: dict[Any, Agent] = {}
    for pu in pus:
        member = make_member(Role.PU_AGENT, scope_ids=[pu.id], organization=org)
        device = Device.objects.create(user=member.user, platform="ANDROID", app_version="1.0.0")
        with system_context():
            AgentAssignment.objects.create(
                organization=org,
                election=election,
                agent=member.user,
                polling_unit=pu,
                ward_id=pu.ward_id,
                lga_id=pu.lga_id,
                assigned_by_id=admin.user.id,
            )
        session = start_session(
            user=member.user,
            membership=member.membership,
            client="MOBILE",
            device=device,
            mfa_at=None,
            ip=None,
        )
        client = CommitClient(capture)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {session.access_token}")
        agents[pu.id] = Agent(member, device, client)
    return Field(
        org=org,
        admin=admin,
        election=election,
        contest=contest,
        candidates=candidates,
        lgas=lgas,
        wards=wards,
        pus=pus,
        agents=agents,
        make_member=make_member,
        client_as=client_as,
        capture=capture,
    )


@pytest.fixture
def field_(make_org, make_member, client_as, django_capture_on_commit_callbacks) -> Field:
    return build_field(
        make_org, make_member, client_as, django_capture_on_commit_callbacks, review_enabled=False
    )


@pytest.fixture
def reviewed_field(make_org, make_member, client_as, django_capture_on_commit_callbacks) -> Field:
    return build_field(
        make_org, make_member, client_as, django_capture_on_commit_callbacks, review_enabled=True
    )


@pytest.fixture
def big_field(make_org, make_member, client_as, django_capture_on_commit_callbacks) -> Field:
    """Twenty polling units: ten per LGA, enough peers for the statistical rules."""
    return build_field(
        make_org,
        make_member,
        client_as,
        django_capture_on_commit_callbacks,
        review_enabled=False,
        polling_units=20,
    )
