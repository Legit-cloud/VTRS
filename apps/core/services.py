"""Transactional outbox and idempotent execution (spec sections 9, 10, 15)."""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from importlib import import_module
from typing import Any
from uuid import UUID

from celery import current_app
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .domain.canonical import to_json_compatible
from .errors import IdempotencyConflict, InvalidIdempotencyKey
from .models import IdempotencyRecord, OutboxEvent

logger = logging.getLogger("vtrs.outbox")

_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


def _require_transaction(what: str) -> None:
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError(f"{what} must run inside the caller's transaction")


# --- Outbox ---------------------------------------------------------------------------------


def emit(topic: str, payload: dict[str, Any]) -> OutboxEvent:
    """Record an event with the business change; it is dispatched once the transaction commits."""
    _require_transaction("Outbox events")
    event = OutboxEvent.objects.create(topic=topic, payload=to_json_compatible(payload))
    transaction.on_commit(lambda: _publish_quietly(event.id))
    return event


def _dispatch(event: OutboxEvent) -> None:
    route = settings.VTRS_OUTBOX_ROUTES.get(event.topic)
    if route is None:
        logger.info("outbox_no_route", extra={"topic": event.topic})
        return
    task_name, queue = route
    args = [str(event.id), event.topic, event.payload]
    if current_app.conf.task_always_eager and _load_task(task_name):
        # Tests and local scripts: run in-process (send_task would only queue a message).
        current_app.tasks[task_name].apply(args=args, throw=True)
        return
    current_app.send_task(task_name, args=args, queue=queue)


def _load_task(task_name: str) -> bool:
    """Task modules load lazily in web processes; import the handler's module if it exists."""
    if task_name not in current_app.tasks:
        try:
            import_module(task_name.rsplit(".", 1)[0])
        except ModuleNotFoundError:
            return False
    return task_name in current_app.tasks


def _publish_quietly(event_id: UUID) -> None:
    # Fast path after commit. A failure here is fine: the relay picks the event up later.
    try:
        event = OutboxEvent.objects.filter(id=event_id, published_at__isnull=True).first()
        if event is None:
            return
        _dispatch(event)
        OutboxEvent.objects.filter(id=event_id, published_at__isnull=True).update(
            published_at=timezone.now()
        )
    except Exception:
        logger.warning("outbox_fast_path_failed", exc_info=True, extra={"event_id": str(event_id)})


def relay_pending(limit: int = 200, min_age_seconds: float | None = None) -> int:
    """Safety net: dispatch unpublished events older than the fast-path window."""
    if min_age_seconds is None:
        min_age_seconds = settings.VTRS_OUTBOX_RELAY_MIN_AGE_SECONDS
    cutoff = timezone.now() - timedelta(seconds=min_age_seconds)
    published = 0
    with transaction.atomic():
        events = list(
            OutboxEvent.objects.select_for_update(skip_locked=True)
            .filter(published_at__isnull=True, created_at__lte=cutoff)
            .order_by("created_at")[:limit]
        )
        for event in events:
            try:
                _dispatch(event)
            except Exception:
                logger.warning(
                    "outbox_relay_failed", exc_info=True, extra={"event_id": str(event.id)}
                )
                OutboxEvent.objects.filter(id=event.id).update(attempts=event.attempts + 1)
                continue
            OutboxEvent.objects.filter(id=event.id).update(
                published_at=timezone.now(), attempts=event.attempts + 1
            )
            published += 1
    return published


def purge_expired() -> dict[str, int]:
    now = timezone.now()
    idempotency, _ = IdempotencyRecord.objects.filter(expires_at__lt=now).delete()
    outbox, _ = OutboxEvent.objects.filter(
        published_at__lt=now - timedelta(days=settings.VTRS_OUTBOX_RETENTION_DAYS)
    ).delete()
    return {"idempotency_records": idempotency, "outbox_events": outbox}


# --- Idempotency ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IdempotentResult:
    status: int
    body: Any
    replayed: bool


def run_idempotent(
    *,
    user_id: UUID,
    scope: str,
    key: str,
    request_hash: str,
    operation: Callable[[], tuple[int, Any]],
) -> IdempotentResult:
    """Run `operation` at most once per (user, scope, key).

    The record is inserted first, inside the same transaction as the operation. A concurrent
    request with the same key blocks on the unique index until the first commits, then replays
    its stored response. If the operation fails, everything rolls back and the key is reusable.
    """
    if not _IDEMPOTENCY_KEY.match(key or ""):
        raise InvalidIdempotencyKey()
    with transaction.atomic():
        try:
            with transaction.atomic():
                record = IdempotencyRecord.objects.create(
                    user_id=user_id,
                    scope=scope,
                    key=key,
                    request_hash=request_hash,
                    expires_at=timezone.now()
                    + timedelta(hours=settings.VTRS_IDEMPOTENCY_TTL_HOURS),
                )
        except IntegrityError:
            existing = IdempotencyRecord.objects.get(user_id=user_id, scope=scope, key=key)
            if existing.request_hash != request_hash:
                raise IdempotencyConflict() from None
            return IdempotentResult(existing.response_status or 200, existing.response_body, True)

        status, body = operation()
        record.response_status = status
        record.response_body = to_json_compatible(body)
        record.save(update_fields=["response_status", "response_body"])
        return IdempotentResult(status, record.response_body, False)
