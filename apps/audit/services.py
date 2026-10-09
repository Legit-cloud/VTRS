"""Audit writer, sealer and verifier (spec sections 6, 16; SEC-06, AC-13)."""

from datetime import timedelta
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from apps.core.context import get_client_ip, get_request_id
from apps.core.domain.actor import Actor
from apps.core.domain.canonical import to_json_compatible

from .domain.merkle import GENESIS_ROOT, LEAF_FIELDS, chain_root, event_leaf, merkle_root
from .models import AuditBatch, AuditEvent

# Arbitrary constant for the transaction-level advisory lock serializing sealers.
_SEAL_LOCK_KEY = 0x7A55_0001


def record(
    *,
    action: str,
    object_type: str,
    object_id: object = "",
    actor: Actor | None = None,
    organization_id: UUID | None = None,
    diff: dict[str, Any] | None = None,
) -> AuditEvent:
    """Write an audit event in the caller's transaction.

    If the event can't be written, the whole action fails with it.
    """
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("Audit events must be written inside the caller's transaction")
    return AuditEvent.objects.create(
        at=timezone.now(),
        actor_id=actor.user_id if actor else None,
        actor_role=str(actor.role) if actor else "",
        organization_id=organization_id or (actor.organization_id if actor else None),
        action=action,
        object_type=object_type,
        object_id=str(object_id),
        ip=get_client_ip(),
        request_id=get_request_id(),
        diff=to_json_compatible(diff or {}),
    )


def _leaf(event: AuditEvent) -> bytes:
    return event_leaf({name: getattr(event, name) for name in LEAF_FIELDS})


def seal_pending(lag_seconds: float | None = None, limit: int | None = None) -> AuditBatch | None:
    """Seal unsealed events into the next batch. Returns None when there is nothing to seal.

    Events are selected by `batch_id IS NULL` rather than by range, so rows from transactions
    that commit late are picked up by a later batch instead of being skipped.
    """
    if lag_seconds is None:
        lag_seconds = settings.VTRS_AUDIT_SEAL_LAG_SECONDS
    if limit is None:
        limit = settings.VTRS_AUDIT_SEAL_BATCH_SIZE
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_SEAL_LOCK_KEY])
        cutoff = timezone.now() - timedelta(seconds=lag_seconds)
        events = list(
            AuditEvent.objects.filter(batch_id__isnull=True, at__lte=cutoff).order_by("id")[:limit]
        )
        if not events:
            return None
        previous = AuditBatch.objects.order_by("-seq").first()
        prev_root = previous.root if previous else GENESIS_ROOT
        batch_root = merkle_root([_leaf(e) for e in events])
        batch = AuditBatch.objects.create(
            seq=(previous.seq + 1) if previous else 1,
            prev_root=prev_root,
            merkle_root=batch_root,
            root=chain_root(prev_root, batch_root),
            event_count=len(events),
            first_event_at=min(e.at for e in events),
            last_event_at=max(e.at for e in events),
        )
        AuditEvent.objects.filter(id__in=[e.id for e in events]).update(batch_id=batch.id)
        return batch


def verify_chain() -> list[str]:
    """Recompute every batch from its events and the chain between batches. Empty = intact."""
    problems: list[str] = []
    prev_root = GENESIS_ROOT
    expected_seq = 1
    for batch in AuditBatch.objects.order_by("seq").iterator():
        label = f"batch {batch.seq}"
        if batch.seq != expected_seq:
            problems.append(f"{label}: expected sequence {expected_seq}")
        if batch.prev_root != prev_root:
            problems.append(f"{label}: does not chain to the previous batch")
        events = list(AuditEvent.objects.filter(batch_id=batch.id).order_by("id"))
        if len(events) != batch.event_count:
            problems.append(f"{label}: holds {len(events)} events, sealed {batch.event_count}")
        if not events or merkle_root([_leaf(e) for e in events]) != batch.merkle_root:
            problems.append(f"{label}: Merkle root mismatch (events altered)")
        if chain_root(batch.prev_root, batch.merkle_root) != batch.root:
            problems.append(f"{label}: chained root mismatch")
        prev_root = batch.root
        expected_seq = batch.seq + 1
    return problems


def ensure_partitions(months_ahead: int | None = None) -> None:
    if months_ahead is None:
        months_ahead = settings.VTRS_AUDIT_PARTITION_MONTHS_AHEAD
    with connection.cursor() as cursor:
        cursor.execute("SELECT audit_ensure_partitions(%s)", [months_ahead])
