"""Result-sheet validation (FR-6.5.1, FR-6.5.2, FR-6.5.5; spec section 10.3).

Pure rules. A submission that breaks one of them is refused with a precise code and a message
that says how to fix it; anything that is valid but suspicious is accepted and flagged by the
anomaly rules instead.

- Every party configured for the election and the unit's constituency appears exactly once:
  no unconfigured party, no missing party, no party twice. (A blank value never reaches here:
  the serializer refuses a missing or null vote count.)
- Party votes plus rejected votes must not exceed total votes cast.
- Total votes cast must not exceed accredited voters.
"""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

# The totals every submission records, as the result sheet shows them. Valid votes are not
# entered: they are the sum of the party votes.
TOTALS = ("accredited", "rejected", "total_cast")


@dataclass(frozen=True, slots=True)
class Problem:
    code: str
    detail: str
    errors: dict[str, Any] = field(default_factory=dict)


def party_problem(
    lines: Sequence[UUID], configured: Iterable[UUID], labels: Mapping[UUID, str]
) -> Problem | None:
    """Check the vote lines (contestant ids, in the order sent) against the configured list."""
    wanted = set(configured)
    repeated = sorted(str(i) for i, n in Counter(lines).items() if n > 1)
    if repeated:
        return Problem(
            "duplicate_party",
            "Each party can appear only once.",
            {"candidate_ids": repeated},
        )
    extra = sorted(str(i) for i in set(lines) - wanted)
    if extra:
        return Problem(
            "unconfigured_party",
            "The result includes a party that is not on this election's list.",
            {"candidate_ids": extra},
        )
    missing = [i for i in wanted - set(lines)]
    if missing:
        names = sorted(labels.get(i, str(i)) for i in missing)
        return Problem(
            "missing_party",
            f"Enter votes for every party on the list, including 0. Missing: {', '.join(names)}.",
            {"candidate_ids": sorted(str(i) for i in missing)},
        )
    return None


def arithmetic_problem(party_votes: int, totals: Mapping[str, int]) -> Problem | None:
    rejected, cast, accredited = totals["rejected"], totals["total_cast"], totals["accredited"]
    if party_votes + rejected > cast:
        return Problem(
            "votes_exceed_total_cast",
            f"Party votes ({party_votes:,}) plus rejected ({rejected:,}) are more than total "
            f"votes cast ({cast:,}). Check the result sheet.",
            {"party_votes": party_votes, "rejected": rejected, "total_cast": cast},
        )
    if cast > accredited:
        return Problem(
            "total_cast_exceeds_accredited",
            f"Total votes cast ({cast:,}) are more than accredited voters ({accredited:,}). "
            "Check the result sheet.",
            {"total_cast": cast, "accredited": accredited},
        )
    return None
