"""Flag reads, narrowed to the caller's geography (AC-11)."""

from datetime import timedelta
from typing import Any
from uuid import UUID

from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, QuerySet
from rest_framework.exceptions import NotFound

from apps.core.authz import authorize
from apps.core.domain.actor import Actor
from apps.core.domain.permissions import Perm

from .models import AnomalyFlag, FlagStatus


def flags_for(actor: Actor) -> QuerySet[AnomalyFlag]:
    authorize(actor, Perm.ANOMALIES_VIEW)
    return AnomalyFlag.objects.for_actor(actor).select_related(
        "polling_unit", "ward", "lga", "contest", "assigned_to"
    )


def flag_for(actor: Actor, flag_id: UUID) -> AnomalyFlag:
    flag = flags_for(actor).prefetch_related("events").filter(id=flag_id).first()
    if flag is None:
        raise NotFound()
    return flag


def summary(actor: Actor, election_id: UUID) -> dict[str, Any]:
    """Counts by status, severity and rule, plus how long flags take to resolve (spec 12)."""
    qs = flags_for(actor).filter(election_id=election_id)
    by_status = {r["status"]: r["n"] for r in qs.values("status").annotate(n=Count("id"))}
    active = qs.filter(status__in=[FlagStatus.OPEN, FlagStatus.ACKNOWLEDGED])
    by_severity = {r["severity"]: r["n"] for r in active.values("severity").annotate(n=Count("id"))}
    by_rule = {r["rule_code"]: r["n"] for r in active.values("rule_code").annotate(n=Count("id"))}
    closed = qs.filter(resolved_at__isnull=False).annotate(
        took=ExpressionWrapper(F("resolved_at") - F("created_at"), output_field=DurationField())
    )
    average: timedelta | None = closed.aggregate(avg=Avg("took"))["avg"]
    overdue = qs.filter(status=FlagStatus.OPEN, escalation_level__gt=0).count()
    unacknowledged_critical = qs.filter(status=FlagStatus.OPEN, severity="CRITICAL").count()
    return {
        "election_id": election_id,
        "by_status": by_status,
        "active_by_severity": by_severity,
        "active_by_rule": by_rule,
        "escalated_open": overdue,
        "unacknowledged_critical": unacknowledged_critical,
        "closed": closed.count(),
        "average_minutes_to_resolve": (
            round(average.total_seconds() / 60, 1) if average is not None else None
        ),
    }
