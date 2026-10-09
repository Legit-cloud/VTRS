"""Merkle roots over audit batches, chained batch to batch (spec section 16).

Leaves and inner nodes use distinct prefixes, and an odd node is promoted rather than
duplicated, so two different event lists can never share a root.
"""

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from apps.core.domain.canonical import canonical_json

GENESIS_ROOT = "0" * 64
_LEAF = b"\x00"
_NODE = b"\x01"

# Columns covered by the hash. batch_id is excluded: the sealer sets it after the fact.
LEAF_FIELDS = (
    "id",
    "at",
    "actor_id",
    "actor_role",
    "organization_id",
    "action",
    "object_type",
    "object_id",
    "ip",
    "request_id",
    "diff",
)


def event_leaf(event: Mapping[str, Any]) -> bytes:
    return canonical_json({name: event[name] for name in LEAF_FIELDS})


def merkle_root(leaves: Sequence[bytes]) -> str:
    if not leaves:
        raise ValueError("A Merkle root needs at least one leaf")
    level = [hashlib.sha256(_LEAF + leaf).digest() for leaf in leaves]
    while len(level) > 1:
        paired = []
        for i in range(0, len(level), 2):
            if i + 1 < len(level):
                paired.append(hashlib.sha256(_NODE + level[i] + level[i + 1]).digest())
            else:
                paired.append(level[i])
        level = paired
    return level[0].hex()


def chain_root(prev_root: str, batch_merkle_root: str) -> str:
    return hashlib.sha256(f"{prev_root}{batch_merkle_root}".encode()).hexdigest()
