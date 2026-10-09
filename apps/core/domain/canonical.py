"""Canonical JSON: one byte representation per value, so hashes are reproducible."""

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID


def _default(value: Any) -> str:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, UUID | Decimal):
        return str(value)
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_default,
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def payload_hash(value: Any) -> str:
    return sha256_hex(canonical_json(value))


def to_json_compatible(value: Any) -> Any:
    """Normalize a value (UUIDs, datetimes, decimals) to plain JSON types."""
    return json.loads(canonical_json(value))
