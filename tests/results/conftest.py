import hashlib
import io
import json
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
from apps.elections.models import Candidate, Contest, Election
from apps.geography.models import PollingUnit
from apps.results.domain.versions import submission_hash

from ..conftest import CommitClient
from ..factories import load_reference_data, make_ballot, make_election

PDF_BYTES = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"


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
    client: CommitClient


def default_totals(votes: list[int] | tuple[int, ...], accredited: int = 210) -> dict[str, int]:
    """Totals that reconcile: party votes + 5 rejected = total cast."""
    return {"accredited": accredited, "rejected": 5, "total_cast": sum(votes) + 5}


def seal(item: dict) -> dict:
    """(Re)compute the payload hash over the item as it will travel (JSON round trip)."""
    body = json.loads(json.dumps({k: v for k, v in item.items() if k != "payload_hash"}))
    return {**body, "payload_hash": submission_hash(body)}


def post_submission(client: CommitClient, item: dict) -> dict:
    """POST one submission; the body is the outcome whatever the status code."""
    response = client.post("/api/v1/submissions", item, format="json")
    body = response.json()
    assert response.status_code == body["http_status"], body
    return body


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
        """A submission exactly as the web app sends it, with a valid payload hash."""
        votes = overrides.pop("votes", [120, 80])
        totals = overrides.pop("totals", default_totals(votes))
        unit = pu or self.pu
        item = {
            "version_id": str(uuid7()),
            "election_id": str(self.election.id),
            "polling_unit_id": str(unit.id),
            "config_version": self.election.config_version,
            "parent_version_id": None,
            "totals": totals,
            "votes": [
                {"candidate_id": str(c.id), "votes": v}
                for c, v in zip(self.candidates, votes, strict=True)
            ],
            "device_captured_at": timezone.now().isoformat(),
            "gps": {
                "lat": float(unit.latitude or 7.39),
                "lng": float(unit.longitude or 3.91),
                "accuracy_m": 12.5,
            },
        }
        item.update(overrides)
        return seal(item)

    def submit(self, *items: dict, agent: Agent | None = None) -> list[dict]:
        client = (agent or self.agent).client
        return [post_submission(client, item) for item in items]


@pytest.fixture
def scenario(make_org, make_member, django_capture_on_commit_callbacks) -> Scenario:
    load_reference_data(lgas=2, wards=2, polling_units=6, seed=11)
    pus = list(PollingUnit.objects.order_by("inec_code"))
    pu, other_pu = pus[0], pus[-1]
    PollingUnit.objects.filter(id=pu.id).update(registered_voters=1000)
    pu.refresh_from_db()
    org = make_org("Results Party")
    admin = make_member(Role.PARTY_ADMIN, organization=org)
    election = make_election(org, admin, config_version=5)
    ballot = make_ballot(org, election, ("AAA", "BBB"), own=None)

    def make_agent(polling_units=(pu,), assign=True) -> Agent:
        member = make_member(
            Role.PU_AGENT, scope_ids=[p.id for p in polling_units], organization=org
        )
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
            user=member.user, membership=member.membership, mfa_at=timezone.now(), ip=None
        )
        client = CommitClient(django_capture_on_commit_callbacks)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {session.access_token}")
        return Agent(member, client)

    return Scenario(
        org=org,
        admin=admin,
        election=election,
        contest=ballot.contest,
        candidates=ballot.candidates,
        pu=pu,
        other_pu=other_pu,
        agent=make_agent(),
        make_agent=make_agent,
    )
