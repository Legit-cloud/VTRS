from typing import Any
from uuid import UUID

from celery import shared_task

from . import services


@shared_task(acks_late=True)
def update_rollups(event_id: str, topic: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Outbox handler for result.version_accepted and result.review_decided.

    Idempotent: it recalculates from head versions, so a repeated or late event only
    rewrites the same figures."""
    if not payload.get("contest_id") or not payload.get("ward_id"):
        return {}  # a flag that is not about a contest has no rollup to refresh
    return services.recompute_ward(
        organization_id=UUID(payload["organization_id"]),
        contest_id=UUID(payload["contest_id"]),
        ward_id=UUID(payload["ward_id"]),
    )


@shared_task(acks_late=True)
def build_election_rollups(event_id: str, topic: str, payload: dict[str, Any]) -> int:
    """Outbox handler for election.opened: create every rollup row before the first result."""
    return services.rebuild_election_by_id(
        organization_id=UUID(payload["organization_id"]),
        election_id=UUID(payload["election_id"]),
    )
