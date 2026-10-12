"""Positions from vote counts: ranking, leader, margin, coverage (FR-6.8.2, FR-6.8.4).

Pure arithmetic. Every figure it produces is a provisional position from party-captured data,
never an official declaration, and callers must carry `PROVISIONAL_NOTICE` with it.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

PROVISIONAL_NOTICE = (
    "Provisional position based on results captured by this party's agents. "
    "It is not an official declaration."
)


class RollupLevel(StrEnum):
    STATE = "STATE"
    LGA = "LGA"
    WARD = "WARD"
    PU = "PU"  # never stored as a rollup: read straight from the polling unit's head version


class Measure(StrEnum):
    """Two counts are always kept (spec section 11). The election's policy picks the default."""

    REPORTED = "REPORTED"  # every counting head: submitted, flagged or approved
    VERIFIED = "VERIFIED"  # only heads a reviewer has approved


@dataclass(frozen=True, slots=True)
class CandidateInfo:
    id: UUID
    name: str
    party_acronym: str
    ballot_order: int
    is_own_party: bool


@dataclass(frozen=True, slots=True)
class Position:
    leader_id: UUID | None
    runner_up_id: UUID | None
    leading_ids: tuple[UUID, ...]  # more than one id means the top spot is tied
    margin: int  # leader minus runner-up; 0 when tied or nobody has votes
    margin_pct: float | None  # of all candidate votes counted; None when there are none
    total_votes: int
    is_tie: bool
    own_margin: int | None  # own candidate minus the best rival; negative when behind


def position(votes: Mapping[UUID, int], candidates: Iterable[CandidateInfo]) -> Position:
    """Rank candidates by votes (ballot order breaks ties in the listing) and derive the lead."""
    info = {c.id: c for c in candidates}
    ranked = sorted(info.values(), key=lambda c: (-votes.get(c.id, 0), c.ballot_order))
    total = sum(votes.get(c.id, 0) for c in ranked)
    if not ranked or total == 0:
        return Position(None, None, (), 0, None, total, False, _own_margin(votes, ranked))
    top = votes.get(ranked[0].id, 0)
    leading = tuple(c.id for c in ranked if votes.get(c.id, 0) == top)
    runner_votes = votes.get(ranked[1].id, 0) if len(ranked) > 1 else 0
    is_tie = len(leading) > 1
    margin = 0 if is_tie else top - runner_votes
    return Position(
        leader_id=None if is_tie else ranked[0].id,
        runner_up_id=ranked[1].id if len(ranked) > 1 else None,
        leading_ids=leading,
        margin=margin,
        margin_pct=round(100 * margin / total, 2),
        total_votes=total,
        is_tie=is_tie,
        own_margin=_own_margin(votes, ranked),
    )


def _own_margin(votes: Mapping[UUID, int], ranked: list[CandidateInfo]) -> int | None:
    own = next((c for c in ranked if c.is_own_party), None)
    if own is None:
        return None
    rivals = [votes.get(c.id, 0) for c in ranked if c.id != own.id]
    return votes.get(own.id, 0) - (max(rivals) if rivals else 0)


def coverage_pct(reported: int, expected: int) -> float:
    """Share of expected polling units that have a counting result."""
    if expected <= 0:
        return 0.0
    return round(100 * reported / expected, 2)


def merge_votes(parts: Iterable[Mapping[Any, int]]) -> dict[Any, int]:
    """Sum per-candidate votes across child areas."""
    merged: dict[Any, int] = {}
    for part in parts:
        for candidate_id, count in part.items():
            merged[candidate_id] = merged.get(candidate_id, 0) + count
    return merged
