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
