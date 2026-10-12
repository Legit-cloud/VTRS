"""A user's own notifications. Nobody reads anyone else's, whatever their role."""

from uuid import UUID

from django.db.models import QuerySet

from apps.core.authz import AUTHENTICATED, authorize
from apps.core.domain.actor import Actor

from .models import Notification


def own_notifications(actor: Actor, *, unread: bool | None = None) -> QuerySet[Notification]:
    authorize(actor, AUTHENTICATED)
    qs = Notification.objects.filter(
        organization_id=actor.organization_id, user_id=actor.user_id
    ).prefetch_related("deliveries")
    if unread is True:
        qs = qs.filter(read_at__isnull=True)
    elif unread is False:
        qs = qs.filter(read_at__isnull=False)
    return qs


def own_notification(actor: Actor, notification_id: UUID) -> Notification | None:
    return own_notifications(actor).filter(id=notification_id).first()


def unread_count(actor: Actor) -> int:
    return own_notifications(actor, unread=True).count()
