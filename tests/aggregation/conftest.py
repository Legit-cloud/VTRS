"""A small election to aggregate: two LGAs, two wards each, two polling units per ward."""

import io
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
from django.utils import timezone
from PIL import Image

from apps.accounts.services.sessions import start_session
from apps.assignments.models import AgentAssignment
from apps.core.domain.permissions import Role
from apps.core.ids import uuid7
from apps.core.rls import system_context
from apps.elections.models import Candidate, Contest, Election, Party
from apps.evidence.models import EvidenceFile
from apps.evidence.storage import get_storage
from apps.geography.models import Lga, PollingUnit, Ward

from ..conftest import CommitClient
from ..factories import load_reference_data, make_ballot, make_election
from ..results.conftest import Agent, manifest_entry, post_submission, seal


@dataclass
class Field:
    org: Any
    admin: Any
    election: Election
    contest: Contest
    candidates: list[Candidate]
    parties: list[Party]
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
        totals = overrides.pop(
            "totals", {"accredited": 400, "rejected": 5, "total_cast": sum(votes) + 5}
        )
        body = {
            "version_id": str(uuid7()),
            "election_id": str(self.election.id),
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
        }
        body.update(overrides)
        return seal(body)

    def submit(self, pu: PollingUnit, votes: tuple[int, int] = (120, 80), **overrides: Any) -> dict:
        item = self.item(pu, votes, **overrides)
        outcome = post_submission(self.agents[pu.id].client, item)
        assert outcome["status"] in {"ACCEPTED", "REQUIRES_REVIEW"}, outcome
        outcome["item"] = item
        return outcome

    def attach_sheet(self, outcome: dict) -> dict:
        """Upload a result sheet for a submission, as the agent's browser does after the
        numbers. A coordinator can verify a result only once its sheet is attached."""
        pu_id = outcome["item"]["polling_unit_id"]
        client = next(a.client for k, a in self.agents.items() if str(k) == pu_id)
        # A textured image per sheet: plain colours look alike to the duplicate-evidence rule.
        rng = random.Random(len(self.extra))  # noqa: S311 - test data
        image = Image.new("RGB", (64, 64))
        image.putdata(
            [(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(64 * 64)]
        )
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=90)
        photo = buffer.getvalue()
        self.extra[outcome["version_id"]] = True
        entry = {**manifest_entry(photo), "version_id": outcome["version_id"]}
        assert client.post("/api/v1/evidence/uploads", entry, format="json").status_code == 200
        with system_context():
            key = EvidenceFile.objects.get(id=entry["evidence_id"]).object_key
        get_storage().write(key, photo, mime="image/jpeg")
        done = client.post(f"/api/v1/evidence/{entry['evidence_id']}/complete")
        assert done.status_code == 200, done.content
        return done.json()

    def verify(self, outcome: dict, client: CommitClient | None = None, **body: Any) -> Any:
        """Attach the sheet, then verify the result as the admin (or `client`)."""
        self.attach_sheet(outcome)
        return (client or self.admin_client()).post(
            f"/api/v1/results/{outcome['version_id']}/review",
            {"decision": "APPROVED", **body},
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid7()),
        )


def build_field(
    make_org,
    make_member,
    client_as,
    capture,
    *,
    polling_units: int = 8,
) -> Field:
    load_reference_data(lgas=2, wards=4, polling_units=polling_units, seed=5)
    lgas = list(Lga.objects.order_by("inec_code"))
    wards = list(Ward.objects.order_by("inec_code"))
    pus = list(PollingUnit.objects.order_by("inec_code"))
    for index, pu in enumerate(pus):
        PollingUnit.objects.filter(id=pu.id).update(registered_voters=500 + index)
    pus = list(PollingUnit.objects.order_by("inec_code"))
    org = make_org("Aggregation Party")
    admin = make_member(Role.PARTY_ADMIN, organization=org, mfa_enabled=True)
    election = make_election(org, admin)
    ballot = make_ballot(org, election, ("AAA", "BBB"), own="AAA")

    agents: dict[Any, Agent] = {}
    for pu in pus:
        member = make_member(Role.PU_AGENT, scope_ids=[pu.id], organization=org)
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
            user=member.user, membership=member.membership, mfa_at=None, ip=None
        )
        client = CommitClient(capture)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {session.access_token}")
        agents[pu.id] = Agent(member, client)
    return Field(
        org=org,
        admin=admin,
        election=election,
        contest=ballot.contest,
        candidates=ballot.candidates,
        parties=ballot.parties,
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
    return build_field(make_org, make_member, client_as, django_capture_on_commit_callbacks)


@pytest.fixture
def reviewed_field(field_) -> Field:
    # Verification is always available now; kept as a name for the review tests.
    return field_


@pytest.fixture
def big_field(make_org, make_member, client_as, django_capture_on_commit_callbacks) -> Field:
    """Twenty polling units: ten per LGA, enough peers for the statistical rules."""
    return build_field(
        make_org,
        make_member,
        client_as,
        django_capture_on_commit_callbacks,
        polling_units=20,
    )
