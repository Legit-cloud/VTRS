from django.db import models
from django.db.models import Q

from apps.core.ids import uuid7
from apps.core.models import UUIDv7Model
from apps.core.scope import ScopedQuerySet

from .domain.inline import RuleCode, Severity


class FlagStatus(models.TextChoices):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    FALSE_POSITIVE = "FALSE_POSITIVE"


class FlagAction(models.TextChoices):
    RAISED = "RAISED"
    ESCALATED = "ESCALATED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ASSIGNED = "ASSIGNED"
    COMMENTED = "COMMENTED"
    RESOLVED = "RESOLVED"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    REOPENED = "REOPENED"


class AnomalyFlag(UUIDv7Model):
    """A finding routed to a human (spec section 13). Triage, escalation and the history of
    what was done about it are tracked here and in `FlagEvent`."""

    SCOPE_LOOKUPS = {
        "org": "organization_id",
        "lga": "lga_id",
        "ward": "ward_id",
        "pu": "polling_unit_id",
    }

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="+"
    )
    election = models.ForeignKey("elections.Election", on_delete=models.PROTECT, related_name="+")
    contest = models.ForeignKey(
        "elections.Contest", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    polling_unit = models.ForeignKey(
        "geography.PollingUnit", on_delete=models.PROTECT, related_name="+"
    )
    ward = models.ForeignKey("geography.Ward", on_delete=models.PROTECT, related_name="+")
    lga = models.ForeignKey("geography.Lga", on_delete=models.PROTECT, related_name="+")
    # Null for attempts that never became a version (e.g. a submit for an unassigned unit).
    result_version = models.ForeignKey(
        "results.ResultVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="flags",
    )
    raised_by_id = models.UUIDField(null=True, blank=True)
    rule_code = models.CharField(max_length=40, choices=[(r.value, r.value) for r in RuleCode])
    rule_version = models.PositiveSmallIntegerField(default=1)
    severity = models.CharField(max_length=10, choices=[(s.value, s.value) for s in Severity])
    details = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=FlagStatus.choices, default=FlagStatus.OPEN)

    # Escalation (spec section 13): the rung of the chain of command reached so far, and when
    # an unacknowledged flag climbs to the next one. `notified_at` makes routing idempotent.
    escalation_level = models.PositiveSmallIntegerField(default=0)
    sla_due_at = models.DateTimeField(null=True, blank=True)
    notified_at = models.DateTimeField(null=True, blank=True)

    # Triage.
    assigned_to = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by_id = models.UUIDField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by_id = models.UUIDField(null=True, blank=True)
    resolution_note = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ScopedQuerySet.as_manager()

    class Meta:
        db_table = "anomaly_flag"
        constraints = [
            models.UniqueConstraint(
                fields=["result_version", "rule_code"],
                condition=Q(status="OPEN") & Q(result_version__isnull=False),
                name="flag_one_open_per_rule",
            )
        ]
        indexes = [
            models.Index(
                fields=["organization", "election", "severity"],
                condition=Q(status="OPEN"),
                name="flag_open_idx",
            ),
            models.Index(fields=["election", "lga"], name="flag_lga_idx"),
            models.Index(
                fields=["sla_due_at"],
                condition=Q(status="OPEN") & Q(sla_due_at__isnull=False),
                name="flag_overdue_idx",
            ),
            models.Index(fields=["result_version", "rule_code"], name="flag_version_rule_idx"),
        ]


class FlagEvent(models.Model):
    """Append-only history of a flag: who raised, escalated, acknowledged, resolved or
    commented, when, and why. The flag row is the current state; this is the record."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="+"
    )
    flag = models.ForeignKey(AnomalyFlag, on_delete=models.PROTECT, related_name="events")
    action = models.CharField(max_length=16, choices=FlagAction.choices)
    from_status = models.CharField(max_length=16, blank=True, default="")
    to_status = models.CharField(max_length=16, blank=True, default="")
    actor_id = models.UUIDField(null=True, blank=True)  # null: raised or escalated by the system
    note = models.TextField(blank=True, default="")
    details = models.JSONField(default=dict, blank=True)
    at = models.DateTimeField()

    class Meta:
        db_table = "anomaly_flag_event"
        indexes = [models.Index(fields=["flag", "at"], name="flag_event_idx")]
