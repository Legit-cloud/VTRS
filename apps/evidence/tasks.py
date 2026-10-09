from typing import Any

from celery import shared_task

from . import services


@shared_task(acks_late=True)
def verify_evidence(event_id: str, topic: str, payload: dict[str, Any]) -> str | None:
    """Outbox handler for evidence.uploaded. Idempotent: re-delivery finds it already done."""
    evidence = services.verify(payload["evidence_id"])
    return evidence.status if evidence else None


@shared_task
def reconcile_pending_uploads() -> int:
    return services.reconcile_pending_uploads()


@shared_task
def ensure_custody_partitions() -> None:
    services.ensure_partitions()
