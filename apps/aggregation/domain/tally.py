"""Positions from vote counts: ranking, leader status, margin, coverage (FR-6.8.2 - FR-6.8.6).

Pure arithmetic over party totals. Every figure it produces is a provisional position from the
party's own captured data, never an official declaration, and callers must carry
`PROVISIONAL_NOTICE` with it. A tie or a narrow lead is reported as such: the status says so,
and no single leader is named for a tie.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

PROVISIONAL_NOTICE = (
    "Provisional figures collected by this party's own agents. "
    "They are not the official INEC count."
)


class RollupLevel(StrEnum):
    STATE = "STATE"
    LGA = "LGA"
    WARD = "WARD"
    PU = "PU"  # never stored as a rollup: read straight from the polling unit's head version


class Measure(StrEnum):
    """Two counts are always kept (spec section 11). The election's policy picks the default."""

    REPORTED = "REPORTED"  # every counting head: submitted, flagged or verified
    VERIFIED = "VERIFIED"  # only heads a coordinator has verified against the sheet


class LeaderStatus(StrEnum):
    NO_VOTES = "NO_VOTES"  # nothing counted yet
    TIED = "TIED"  # two or more parties share the top
    NARROW = "NARROW"  # a lead at or below the narrow-margin threshold
    LEADING = "LEADING"


@dataclass(frozen=True, slots=True)
class PartyInfo:
    id: UUID
    abbreviation: str
    ballot_order: int
    is_own: bool


@dataclass(frozen=True, slots=True)
class Position:
    status: LeaderStatus
    leader_id: UUID | None  # None unless LEADING or NARROW
    runner_up_id: UUID | None
    leading_ids: tuple[UUID, ...]  # every party sharing the top
    margin: int  # leader minus runner-up; 0 when tied or nobody has votes
    margin_pct: float | None  # of all party votes counted; None when there are none
    total_votes: int
    own_margin: int | None  # own party minus the best rival; negative when behind

    @property
    def is_tie(self) -> bool:
        return self.status is LeaderStatus.TIED


def position(
    votes: Mapping[UUID, int], parties: Iterable[PartyInfo], *, narrow_pct: float
) -> Position:
    """Rank parties by votes (ballot order breaks ties in the listing) and derive the lead.

    A lead of `narrow_pct` percent of the counted votes or less is NARROW."""
    info = {p.id: p for p in parties}
    ranked = sorted(info.values(), key=lambda p: (-votes.get(p.id, 0), p.ballot_order))
    total = sum(votes.get(p.id, 0) for p in ranked)
    own = _own_margin(votes, ranked)
    if not ranked or total == 0:
        return Position(LeaderStatus.NO_VOTES, None, None, (), 0, None, total, own)
    top = votes.get(ranked[0].id, 0)
    leading = tuple(p.id for p in ranked if votes.get(p.id, 0) == top)
    runner_up = ranked[1].id if len(ranked) > 1 else None
    if len(leading) > 1:
        return Position(LeaderStatus.TIED, None, runner_up, leading, 0, 0.0, total, own)
    margin = top - (votes.get(ranked[1].id, 0) if len(ranked) > 1 else 0)
    margin_pct = round(100 * margin / total, 2)
    status = LeaderStatus.NARROW if margin_pct <= narrow_pct else LeaderStatus.LEADING
    return Position(status, ranked[0].id, runner_up, leading, margin, margin_pct, total, own)


def _own_margin(votes: Mapping[UUID, int], ranked: list[PartyInfo]) -> int | None:
    own = next((p for p in ranked if p.is_own), None)
    if own is None:
        return None
    rivals = [votes.get(p.id, 0) for p in ranked if p.id != own.id]
    return votes.get(own.id, 0) - (max(rivals) if rivals else 0)


def coverage_pct(reported: int, expected: int) -> float:
    """Share of expected polling units that have a counting result."""
    if expected <= 0:
        return 0.0
    return round(100 * reported / expected, 2)


def merge_votes(parts: Iterable[Mapping[Any, int]]) -> dict[Any, int]:
    """Sum per-party (or per-contestant) votes across child areas or contests."""
    merged: dict[Any, int] = {}
    for part in parts:
        for key, count in part.items():
            merged[key] = merged.get(key, 0) + count
    return merged
