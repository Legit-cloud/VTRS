from typing import Any
from uuid import UUID

from celery import shared_task

from . import analysis, routing


@shared_task(acks_late=True)
def analyze_version(event_id: str, topic: str, payload: dict[str, Any]) -> int:
    """Outbox handler for result.version_accepted. Idempotent: one flag per (version, rule)."""
    return analysis.analyze_version(UUID(payload["organization_id"]), UUID(payload["version_id"]))


@shared_task(acks_late=True)
def analyze_evidence(event_id: str, topic: str, payload: dict[str, Any]) -> int:
    """Outbox handler for evidence.verified."""
    return analysis.analyze_evidence(UUID(payload["organization_id"]), UUID(payload["evidence_id"]))


@shared_task(acks_late=True)
def flag_quarantined(event_id: str, topic: str, payload: dict[str, Any]) -> int:
    """Outbox handler for evidence.quarantined."""
    return analysis.flag_quarantined(UUID(payload["organization_id"]), UUID(payload["evidence_id"]))


@shared_task(acks_late=True)
def route_flags(event_id: str, topic: str, payload: dict[str, Any]) -> int:
    """Outbox handler for anomaly.flags_raised: tell the right people, start the clock."""
    return routing.route_flags(
        UUID(payload["organization_id"]), [UUID(i) for i in payload["flag_ids"]]
    )


@shared_task
def escalate_overdue() -> int:
    return routing.escalate_overdue()


@shared_task
def check_missing_evidence() -> int:
    return analysis.check_missing_evidence()
