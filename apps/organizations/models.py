from django.db import models

from apps.core.models import UUIDv7Model
from apps.core.scope import ScopedQuerySet


class OrganizationStatus(models.TextChoices):
    # Registered; the signer has not verified the OTP yet.
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    # Signer verified; waiting for a platform operator to approve.
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    # Turned away at the approval step; the reason is kept on the organization.
    REJECTED = "REJECTED"


class Organization(UUIDv7Model):
    """A party (tenant). Every tenant table carries organization_id; RLS isolates them."""

    SCOPE_LOOKUPS = {"org": "id"}

    name = models.CharField(max_length=200)
    legal_name = models.CharField(max_length=200, blank=True, default="")
    status = models.CharField(
        max_length=24,
        choices=OrganizationStatus.choices,
        default=OrganizationStatus.PENDING_VERIFICATION,
    )
    # The organization that holds the platform operators. Exactly one, never a party.
    is_platform = models.BooleanField(default=False)
    status_reason = models.CharField(max_length=500, blank=True, default="")
    verified_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ScopedQuerySet.as_manager()

    class Meta:
        db_table = "organization"
        constraints = [
            models.UniqueConstraint(
                fields=["is_platform"],
                condition=models.Q(is_platform=True),
                name="one_platform_org",
            )
        ]

    def __str__(self) -> str:
        return self.name
