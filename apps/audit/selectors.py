"""Audit log reads (FR-6.11.4, spec section 13). Organization admins see their own
organization's events only; the table is partitioned by month, so every query is bounded by a
time window."""

from datetime import datetime, timedelta
from uuid import UUID

from django.db.models import QuerySet
from rest_framework.exceptions import ValidationError

from apps.core.authz import authorize
from apps.core.domain.actor import Actor
from apps.core.domain.permissions import Perm

from .models import AuditEvent

MAX_WINDOW = timedelta(days=31)


def events_for(
    actor: Actor,
    *,
    since: datetime,
    until: datetime,
    action: str | None = None,
    actor_id: UUID | None = None,
    object_type: str | None = None,
    object_id: str | None = None,
) -> QuerySet[AuditEvent]:
    authorize(actor, Perm.AUDIT_VIEW)
    if until <= since:
        raise ValidationError({"until": ["`until` must be after `since`."]})
    if until - since > MAX_WINDOW:
        raise ValidationError({"since": ["The window is limited to 31 days."]})
    qs = AuditEvent.objects.filter(
        organization_id=actor.organization_id, at__gte=since, at__lt=until
    )
    if action:
        qs = qs.filter(action__startswith=action)
    if actor_id:
        qs = qs.filter(actor_id=actor_id)
    if object_type:
        qs = qs.filter(object_type=object_type)
    if object_id:
        qs = qs.filter(object_id=object_id)
    return qs
