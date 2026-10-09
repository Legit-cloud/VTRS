import hashlib
import io
import json
from dataclasses import dataclass, field
from typing import Any

import pytest
from PIL import Image

from apps.accounts.models import Device
from apps.accounts.services.sessions import start_session
from apps.assignments.models import AgentAssignment
from apps.core.domain.permissions import Role
from apps.core.ids import uuid7
from apps.core.rls import system_context
from apps.elections.models import Candidate, Contest, Election
from apps.geography.domain.synthetic import synthetic_master_data
from apps.geography.models import PollingUnit, State
from apps.geography.services import import_master_data
from apps.results.domain.versions import submission_hash

from ..conftest import CommitClient


def jpeg_bytes(size=(240, 160), color=(200, 30, 30), exif: bytes | None = None) -> bytes:
    buffer = io.BytesIO()
    image = Image.new("RGB", size, color)
    if exif:
        image.save(buffer, format="JPEG", exif=exif)
    else:
        image.save(buffer, format="JPEG")
    return buffer.getvalue()


def manifest_entry(data: bytes, mime: str = "image/jpeg", kind: str = "EC8A") -> dict[str, Any]:
    return {
        "evidence_id": str(uuid7()),
        "kind": kind,
        "size": len(data),
        "mime": mime,
        "sha256": hashlib.sha256(data).hexdigest(),
    }


@dataclass
class Agent:
    member: Any
    device: Device
    client: CommitClient


@dataclass
class Scenario:
    org: Any
    admin: Any
    election: Election
    contest: Contest
    candidates: list[Candidate]
    pu: PollingUnit
    other_pu: PollingUnit
    agent: Agent
    make_agent: Any
    extra: dict = field(default_factory=dict)

    def item(
        self, *, agent: Agent | None = None, pu: PollingUnit | None = None, **overrides: Any
    ) -> dict:
        """A submission item exactly as the app would send it, with a valid payload hash."""
        agent = agent or self.agent
        votes = overrides.pop("votes", [120, 80])
        totals = overrides.pop(
            "totals",
            {"accredited": 210, "valid": sum(votes), "rejected": 5, "total_cast": sum(votes) + 5},
        )
        item = {
            "version_id": str(uuid7()),
            "contest_id": str(self.contest.id),
            "polling_unit_id": str((pu or self.pu).id),
            "config_version": self.election.config_version,
            "parent_version_id": None,
            "totals": totals,
            "votes": [
                {"candidate_id": str(c.id), "votes": v}
                for c, v in zip(self.candidates, votes, strict=True)
            ],
            "device_captured_at": "2027-03-11T15:42:10+01:00",
            "gps": {"lat": 7.3912, "lng": 3.9157, "accuracy_m": 12.5},
            "device_id": str(agent.device.id),
            "app_version": "1.0.0",
            "evidence": [],
        }
        item.update(overrides)
        return seal(item)

    def submit(self, *items: dict, agent: Agent | None = None) -> list[dict]:
        response = (agent or self.agent).client.post(
            "/api/v1/sync/submissions", {"items": list(items)}, format="json"
        )
        assert response.status_code == 200, response.content
        return response.json()["items"]


def seal(item: dict) -> dict:
    """(Re)compute the payload hash over the item as it will travel (JSON round trip)."""
    body = json.loads(json.dumps({k: v for k, v in item.items() if k != "payload_hash"}))
    return {**body, "payload_hash": submission_hash(body)}


@pytest.fixture
def scenario(make_org, make_member, django_capture_on_commit_callbacks) -> Scenario:
    import_master_data(synthetic_master_data(lgas=2, wards=2, polling_units=6, seed=11))
    pus = list(PollingUnit.objects.order_by("inec_code"))
    pu, other_pu = pus[0], pus[-1]
    PollingUnit.objects.filter(id=pu.id).update(registered_voters=1000)
    pu.refresh_from_db()
    org = make_org("Results Party")
    admin = make_member(Role.PARTY_ADMIN, organization=org)
    with system_context():
        election = Election.objects.create(
            organization=org,
            name="Governorship",
            state=State.objects.get(),
            election_date="2027-03-11",
            status="LIVE",
            config_version=5,
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
                config_version=1,
            )
            for order, acr in ((1, "AAA"), (2, "BBB"))
        ]

    def make_agent(polling_units=(pu,), assign=True) -> Agent:
        member = make_member(
            Role.PU_AGENT, scope_ids=[p.id for p in polling_units], organization=org
        )
        device = Device.objects.create(user=member.user, platform="ANDROID", app_version="1.0.0")
        if assign:
            with system_context():
                for unit in polling_units:
                    AgentAssignment.objects.create(
                        organization=org,
                        election=election,
                        agent=member.user,
                        polling_unit=unit,
                        ward_id=unit.ward_id,
                        lga_id=unit.lga_id,
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
        client = CommitClient(django_capture_on_commit_callbacks)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {session.access_token}")
        return Agent(member, device, client)

    return Scenario(
        org=org,
        admin=admin,
        election=election,
        contest=contest,
        candidates=candidates,
        pu=pu,
        other_pu=other_pu,
        agent=make_agent(),
        make_agent=make_agent,
    )
