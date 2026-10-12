"""Result versions: states, head selection and the payload hash (spec sections 10, 11).

A polling unit's result is an append-only ledger of versions. Corrections are new versions;
nothing is edited or deleted. The head (the version that counts) is the highest version_no
that has not been rejected, so rejecting the latest falls back to the one before it.
"""

from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import Any
from uuid import UUID

from apps.core.domain.canonical import payload_hash


class VersionState(StrEnum):
    SUBMITTED = "SUBMITTED"  # accepted, no flags
    REQUIRES_REVIEW = "REQUIRES_REVIEW"  # accepted, flagged for a human
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# Head versions in these states count towards the "Reported" measure (section 11).
REPORTED_STATES = frozenset(
    {VersionState.SUBMITTED, VersionState.REQUIRES_REVIEW, VersionState.APPROVED}
)


class ReviewDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# A head can be approved from these states, and rejected from these or after approval.
APPROVABLE_STATES = frozenset({VersionState.SUBMITTED, VersionState.REQUIRES_REVIEW})
REJECTABLE_STATES = APPROVABLE_STATES | {VersionState.APPROVED}
# Verified measure (section 11): only reviewed-and-approved heads.
VERIFIED_STATES = frozenset({VersionState.APPROVED})


def decided_state(current: str, decision: ReviewDecision) -> VersionState | None:
    """The state a review decision moves a version to, or None if it is not allowed."""
    state = VersionState(current)
    if decision is ReviewDecision.APPROVED:
        return VersionState.APPROVED if state in APPROVABLE_STATES else None
    return VersionState.REJECTED if state in REJECTABLE_STATES else None


def is_fork(parent_id: UUID | None, *, head_id: UUID | None, latest_id: UUID | None) -> bool:
    """Whether a submission's declared parent contradicts the ledger.

    A new version legitimately follows either the head (a correction) or the latest version
    (a resubmission after that version was rejected, so it is no longer the head).
    """
    if latest_id is None:
        return parent_id is not None
    return parent_id not in {head_id, latest_id}


def select_head(versions: Iterable[tuple[int, str, UUID]]) -> UUID | None:
    """(version_no, state, id) triples -> id of the head, or None if every version is rejected."""
    candidates = [v for v in versions if v[1] != VersionState.REJECTED]
    if not candidates:
        return None
    return max(candidates, key=lambda v: v[0])[2]


def submission_hash(item: Mapping[str, Any]) -> str:
    """The payload hash the device sends: SHA-256 (hex) of the submission item, without its
    `payload_hash` field, as canonical JSON (keys sorted, no whitespace, UTF-8). Hashing the
    item exactly as sent keeps the device and server in agreement on number and date formats.
    """
    return payload_hash({k: v for k, v in item.items() if k != "payload_hash"})
