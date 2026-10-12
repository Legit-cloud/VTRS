from typing import Any
from uuid import UUID

from celery import shared_task

from . import services


@shared_task(acks_late=True, soft_time_limit=1500, time_limit=1800)
def build_export(event_id: str, topic: str, payload: dict[str, Any]) -> str:
    """Outbox handler for export.requested. Idempotent: only a PENDING job is built."""
    return services.run_export(UUID(payload["organization_id"]), UUID(payload["job_id"]))


@shared_task
def purge_expired_exports() -> int:
    return services.purge_expired()
