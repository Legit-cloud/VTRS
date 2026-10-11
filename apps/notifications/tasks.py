from typing import Any
from uuid import UUID

from celery import shared_task

from . import services


@shared_task(acks_late=True)
def deliver_notifications(event_id: str, topic: str, payload: dict[str, Any]) -> int:
    """Outbox handler for notification.created. Idempotent: sent deliveries are not resent."""
    return services.deliver(
        UUID(payload["organization_id"]), [UUID(i) for i in payload["notification_ids"]]
    )


@shared_task
def retry_failed_deliveries() -> int:
    return services.retry_failed()
