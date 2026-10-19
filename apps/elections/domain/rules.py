"""Election configuration rules (FR-6.3.1 - FR-6.3.7, spec section 11).

Lifecycle: DRAFT <-> CONFIGURED -> LOCKED -> LIVE -> CLOSED -> RECONCILED.
Contesting parties, contests and contestants can change only before LOCKED. Locking records a
fingerprint of the whole configuration, so any later difference is detectable.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID

from apps.core.domain.canonical import payload_hash


class ElectionStatus(StrEnum):
    DRAFT = "DRAFT"
    CONFIGURED = "CONFIGURED"
    LOCKED = "LOCKED"
    LIVE = "LIVE"
    CLOSED = "CLOSED"
    RECONCILED = "RECONCILED"


# RECONCILED snapshots the rollups and freezes results; it has its own endpoint.
TRANSITIONS: Mapping[ElectionStatus, frozenset[ElectionStatus]] = {
    ElectionStatus.DRAFT: frozenset({ElectionStatus.CONFIGURED}),
    ElectionStatus.CONFIGURED: frozenset({ElectionStatus.DRAFT, ElectionStatus.LOCKED}),
    ElectionStatus.LOCKED: frozenset({ElectionStatus.LIVE}),
    ElectionStatus.LIVE: frozenset({ElectionStatus.CLOSED}),
    ElectionStatus.CLOSED: frozenset({ElectionStatus.RECONCILED}),
    ElectionStatus.RECONCILED: frozenset(),
}

# Contesting parties, contests and contestants may change only in these states (FR-6.3.3).
EDITABLE = frozenset({ElectionStatus.DRAFT, ElectionStatus.CONFIGURED})
# Agents can be deployed until polls close.
ASSIGNABLE = frozenset(
    {ElectionStatus.DRAFT, ElectionStatus.CONFIGURED, ElectionStatus.LOCKED, ElectionStatus.LIVE}
)


def can_transition(current: ElectionStatus, target: ElectionStatus) -> bool:
    return target in TRANSITIONS[current]


class IssueKind(StrEnum):
    """What an agent reports when the result form does not match the sheet (FR-6.3.7)."""

    PARTY_MISSING = "PARTY_MISSING"
    CONTESTANT_MISSING = "CONTESTANT_MISSING"


class IssueStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


def normalize_abbreviation(raw: str) -> str:
    """Party abbreviations are compared and stored upper case, without surrounding spaces."""
    return raw.strip().upper()


@dataclass(frozen=True)
class ContestantSpec:
    id: UUID
    name: str
    party_id: UUID


@dataclass(frozen=True)
class ContestSpec:
    id: UUID
    constituency_id: UUID
    constituency_name: str
    contestants: tuple[ContestantSpec, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PartySpec:
    party_id: UUID
    abbreviation: str
    ballot_order: int


def configuration_problems(
    parties: Sequence[PartySpec], contests: Sequence[ContestSpec]
) -> list[str]:
    """Everything that stops an election from being CONFIGURED or LOCKED."""
    problems = []
    if len(parties) < 2:
        problems.append("the election needs at least two contesting parties")
    if not contests:
        problems.append("no constituency has contestants yet")
    contesting = {p.party_id for p in parties}
    for contest in contests:
        label = f"constituency {contest.constituency_name!r}"
        if len(contest.contestants) < 2:
            problems.append(f"{label} needs contestants from at least two parties")
        stray = [c.name for c in contest.contestants if c.party_id not in contesting]
        if stray:
            problems.append(f"{label}: {', '.join(stray)} stand for a party not contesting")
    return problems


def fingerprint(
    election_id: UUID, parties: Sequence[PartySpec], contests: Sequence[ContestSpec]
) -> str:
    """SHA-256 over a canonical view of the configuration, recorded when the election locks."""
    snapshot: dict[str, Any] = {
        "election": election_id,
        "parties": [
            {"party_id": p.party_id, "abbreviation": p.abbreviation, "ballot_order": p.ballot_order}
            for p in sorted(parties, key=lambda p: p.ballot_order)
        ],
        "contests": [
            {
                "id": c.id,
                "constituency_id": c.constituency_id,
                "contestants": [
                    {"id": k.id, "name": k.name, "party_id": k.party_id}
                    for k in sorted(c.contestants, key=lambda k: str(k.party_id))
                ],
            }
            for c in sorted(contests, key=lambda c: str(c.id))
        ],
    }
    return payload_hash(snapshot)
