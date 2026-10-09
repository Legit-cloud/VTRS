"""Evidence rules (spec section 12): accepted formats, object keys, and the custody hash chain."""

import hashlib
from collections.abc import Mapping
from enum import StrEnum
from typing import Any
from uuid import UUID

from apps.core.domain.canonical import canonical_json

MAX_BYTES = 8 * 1024 * 1024
GENESIS_HASH = "0" * 64


class EvidenceKind(StrEnum):
    EC8A = "EC8A"
    EC8B = "EC8B"
    EC8C = "EC8C"


class EvidenceStatus(StrEnum):
    PENDING_UPLOAD = "PENDING_UPLOAD"
    UPLOADED = "UPLOADED"
    VERIFIED = "VERIFIED"
    QUARANTINED = "QUARANTINED"


# MIME type -> (file extension, magic-byte check)
ALLOWED_TYPES: Mapping[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


def sniff_mime(head: bytes) -> str | None:
    """Identify an image by its leading bytes, never by what the client claims."""
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def object_key(
    *,
    organization_id: UUID,
    election_id: UUID,
    polling_unit_id: UUID,
    version_id: UUID,
    evidence_id: UUID,
    mime: str,
) -> str:
    # No personal data in keys, and nothing relies on keys being secret.
    return (
        f"org/{organization_id}/election/{election_id}/pu/{polling_unit_id}/"
        f"{version_id}/{evidence_id}.{ALLOWED_TYPES[mime]}"
    )


def custody_hash(prev_hash: str, event: Mapping[str, Any]) -> str:
    """hash = SHA-256(prev_hash + canonical event). Each file has its own chain."""
    return hashlib.sha256(prev_hash.encode() + canonical_json(dict(event))).hexdigest()
