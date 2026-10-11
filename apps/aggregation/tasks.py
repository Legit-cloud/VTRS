from typing import Any
from uuid import UUID

from celery import shared_task

from . import services


@shared_task(acks_late=True)
def update_rollups(event_id: str, topic: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Outbox handler for result.version_accepted, result.review_decided and flag changes.

    It marks the ward and refreshes whatever is marked. If another worker is already refreshing
    this contest it returns at once: that worker drains marks in a loop, and a periodic sweep
    covers the rare mark that lands after its last look. (Retrying with a delay was tried and
    is worse: delayed tasks fill the worker's prefetch window and starve everything else.)
    Idempotent: it recalculates from head versions."""
    if not payload.get("contest_id") or not payload.get("ward_id"):
        return {}  # a flag that is not about a contest has no rollup to refresh
    return services.recompute_ward(
        organization_id=UUID(payload["organization_id"]),
        contest_id=UUID(payload["contest_id"]),
        ward_id=UUID(payload["ward_id"]),
        wait=False,
    )


@shared_task
def drain_stale_marks() -> int:
    return services.drain_stale()


@shared_task
def self_heal_rollups() -> dict[str, int]:
    return services.self_heal_live_contests()


@shared_task(acks_late=True)
def build_election_rollups(event_id: str, topic: str, payload: dict[str, Any]) -> int:
    """Outbox handler for election.opened: create every rollup row before the first result."""
    return services.rebuild_election_by_id(
        organization_id=UUID(payload["organization_id"]),
        election_id=UUID(payload["election_id"]),
    )
