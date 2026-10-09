"""Election configuration rules (FR-6.3.1 - FR-6.3.3, spec section 11).

Lifecycle: DRAFT <-> CONFIGURED -> LOCKED -> LIVE -> CLOSED (-> RECONCILED, with M4).
Contests and candidates can change only before LOCKED. Locking records a fingerprint of the
whole configuration, so any later difference is detectable.
"""

from collections.abc import Iterable, Mapping, Sequence
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


# RECONCILED snapshots the rollups, so it arrives with aggregation (M4).
TRANSITIONS: Mapping[ElectionStatus, frozenset[ElectionStatus]] = {
    ElectionStatus.DRAFT: frozenset({ElectionStatus.CONFIGURED}),
    ElectionStatus.CONFIGURED: frozenset({ElectionStatus.DRAFT, ElectionStatus.LOCKED}),
    ElectionStatus.LOCKED: frozenset({ElectionStatus.LIVE}),
    ElectionStatus.LIVE: frozenset({ElectionStatus.CLOSED}),
    ElectionStatus.CLOSED: frozenset(),
    ElectionStatus.RECONCILED: frozenset(),
}

# Contests and candidates may change only in these states (FR-6.3.3).
EDITABLE = frozenset({ElectionStatus.DRAFT, ElectionStatus.CONFIGURED})
# Agents can be deployed until polls close.
ASSIGNABLE = frozenset(
    {ElectionStatus.DRAFT, ElectionStatus.CONFIGURED, ElectionStatus.LOCKED, ElectionStatus.LIVE}
)


def can_transition(current: ElectionStatus, target: ElectionStatus) -> bool:
    return target in TRANSITIONS[current]


class JurisdictionLevel(StrEnum):
    STATE = "STATE"
    LGA = "LGA"
    WARD = "WARD"


# Result-sheet totals a contest can capture (PB-05 decides the final set per form).
SHEET_FIELDS = ("accredited", "valid", "rejected", "total_cast")
REQUIRED_SHEET_FIELDS = frozenset({"valid"})


def sheet_field_problems(fields: Sequence[str]) -> list[str]:
    problems = [f"unknown result field {f!r}" for f in fields if f not in SHEET_FIELDS]
    if len(set(fields)) != len(fields):
        problems.append("result fields repeat")
    missing = REQUIRED_SHEET_FIELDS - set(fields)
    if missing:
        problems.append(f"result fields must include {sorted(missing)}")
    return problems


def covers(
    level: JurisdictionLevel,
    jurisdiction_ids: Iterable[UUID],
    *,
    state_id: UUID,
    lga_id: UUID,
    ward_id: UUID,
) -> bool:
    """Whether a contest's jurisdiction includes a polling unit."""
    target = {
        JurisdictionLevel.STATE: state_id,
        JurisdictionLevel.LGA: lga_id,
        JurisdictionLevel.WARD: ward_id,
    }[level]
    return target in set(jurisdiction_ids)


@dataclass(frozen=True)
class CandidateSpec:
    id: UUID
    name: str
    party_acronym: str
    ballot_order: int
    is_own_party: bool


@dataclass(frozen=True)
class ContestSpec:
    id: UUID
    office: str
    title: str
    jurisdiction_level: str
    jurisdiction_ids: tuple[UUID, ...]
    sheet_fields: tuple[str, ...]
    candidates: tuple[CandidateSpec, ...] = field(default_factory=tuple)


def configuration_problems(contests: Sequence[ContestSpec]) -> list[str]:
    """Everything that stops an election from being CONFIGURED or LOCKED."""
    if not contests:
        return ["the election has no contests"]
    problems = []
    for contest in contests:
        label = f"contest {contest.title!r}"
        if not contest.jurisdiction_ids:
            problems.append(f"{label} has no jurisdiction")
        if len(contest.candidates) < 2:
            problems.append(f"{label} needs at least two candidates")
        if sum(c.is_own_party for c in contest.candidates) > 1:
            problems.append(f"{label} marks more than one candidate as the party's own")
        problems.extend(f"{label}: {p}" for p in sheet_field_problems(contest.sheet_fields))
    return problems


def fingerprint(election_id: UUID, contests: Sequence[ContestSpec]) -> str:
    """SHA-256 over a canonical view of the configuration, recorded when the election locks."""
    snapshot: dict[str, Any] = {
        "election": election_id,
        "contests": [
            {
                "id": c.id,
                "office": c.office,
                "title": c.title,
                "jurisdiction_level": c.jurisdiction_level,
                "jurisdiction_ids": sorted(str(i) for i in c.jurisdiction_ids),
                "sheet_fields": list(c.sheet_fields),
                "candidates": [
                    {
                        "id": k.id,
                        "name": k.name,
                        "party_acronym": k.party_acronym,
                        "ballot_order": k.ballot_order,
                        "is_own_party": k.is_own_party,
                    }
                    for k in sorted(c.candidates, key=lambda k: k.ballot_order)
                ],
            }
            for c in sorted(contests, key=lambda c: str(c.id))
        ],
    }
    return payload_hash(snapshot)
