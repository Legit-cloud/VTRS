from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import UUIDv7Model
from apps.core.scope import ScopedQuerySet


class AssignmentStatus(models.TextChoices):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class AgentAssignment(UUIDv7Model):
    """An agent deployed to a polling unit for one election (FR-6.2.4).

    Ward and LGA are denormalized so geographic scoping is one indexed predicate.
    """

    SCOPE_LOOKUPS = {
        "org": "organization_id",
        "lga": "lga_id",
        "ward": "ward_id",
        "pu": "polling_unit_id",
    }

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="+"
    )
    election = models.ForeignKey(
        "elections.Election", on_delete=models.PROTECT, related_name="assignments"
    )
    agent = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="assignments")
    polling_unit = models.ForeignKey(
        "geography.PollingUnit", on_delete=models.PROTECT, related_name="+"
    )
    ward = models.ForeignKey("geography.Ward", on_delete=models.PROTECT, related_name="+")
    lga = models.ForeignKey("geography.Lga", on_delete=models.PROTECT, related_name="+")
    status = models.CharField(
        max_length=8, choices=AssignmentStatus.choices, default=AssignmentStatus.ACTIVE
    )
    assigned_by_id = models.UUIDField()
    valid_from = models.DateTimeField(default=timezone.now)
    valid_to = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ScopedQuerySet.as_manager()

    class Meta:
        db_table = "agent_assignment"
        constraints = [
            models.UniqueConstraint(
                fields=["election", "agent", "polling_unit"],
                condition=Q(status="ACTIVE"),
                name="assignment_unique_active",
            ),
            models.CheckConstraint(
                condition=Q(valid_to__isnull=True) | Q(valid_to__gt=models.F("valid_from")),
                name="assignment_validity_window",
            ),
        ]
        indexes = [
            models.Index(
                fields=["election", "polling_unit"],
                condition=Q(status="ACTIVE"),
                name="assignment_pu_active_idx",
            ),
            models.Index(
                fields=["agent"], condition=Q(status="ACTIVE"), name="assignment_agent_active_idx"
            ),
            models.Index(fields=["election", "lga"], name="assignment_lga_idx"),
            models.Index(fields=["election", "ward"], name="assignment_ward_idx"),
        ]
