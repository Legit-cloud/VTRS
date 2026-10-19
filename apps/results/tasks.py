from typing import Any
from uuid import UUID

from celery import shared_task
from django.db import transaction

from apps.core import rls
from apps.notifications import services as notifications
from apps.notifications.models import Notification, NotificationKind

from .models import ResultReview


@shared_task(acks_late=True)
def notify_review_decision(event_id: str, topic: str, payload: dict[str, Any]) -> int:
    """Outbox handler for result.review_decided: tell the agent what happened to their result.

    A rejection goes to the agent's phone (push) and inbox with the reviewer's reason, so they
    can correct and resubmit. An approval is an inbox entry only. Idempotent: one notification
    per review row."""
    organization_id = UUID(payload["organization_id"])
    with transaction.atomic():
        rls.set_tenant(organization_id)
        review = (
            ResultReview.objects.select_related("result_version", "polling_unit")
            .filter(result_version_id=UUID(payload["version_id"]))
            .order_by("-decided_at")
            .first()
        )
        if review is None:
            return 0
        marker = str(review.id)
        if Notification.objects.filter(
            user_id=review.result_version.submitted_by_id, data__review_id=marker
        ).exists():
            return 0
        rejected = review.decision == "REJECTED"
        created = notifications.notify(
            organization_id=organization_id,
            user_ids=[review.result_version.submitted_by_id],
            kind=NotificationKind.RESULT_REJECTED if rejected else NotificationKind.RESULT_APPROVED,
            title="Result rejected: please correct and resubmit" if rejected else "Result approved",
            body=(
                f"{review.polling_unit.name}: {review.reason}"
                if rejected
                else f"{review.polling_unit.name}: your result was approved."
            ),
            data={
                "review_id": marker,
                "version_id": str(review.result_version_id),
                "polling_unit_id": str(review.polling_unit_id),
            },
            channels=[],
        )
        return len(created)
