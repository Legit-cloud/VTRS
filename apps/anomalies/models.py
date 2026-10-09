from django.db import models
from django.db.models import Q

from apps.core.models import UUIDv7Model
from apps.core.scope import ScopedQuerySet

from .domain.inline import RuleCode, Severity


class FlagStatus(models.TextChoices):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    FALSE_POSITIVE = "FALSE_POSITIVE"


class AnomalyFlag(UUIDv7Model):
    """A finding routed to a human (spec section 13). Triage workflow arrives with M5."""

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
        ]
