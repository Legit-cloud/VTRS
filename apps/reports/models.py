"""Export jobs (FR-6.10.5, spec section 14).

An export is a background job, not a response body: building one can take minutes, touches
evidence, and must be reviewable afterwards. The requester's authority is snapshotted on the
job (role, scope, grants) so the worker builds exactly what they were allowed to see when they
asked, whatever changes while it runs.
"""

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q

from apps.core.models import UUIDv7Model


class JobStatus(models.TextChoices):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    READY = "READY"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class ExportJob(UUIDv7Model):
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="+"
    )
    requested_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=16)
    format = models.CharField(max_length=4)
    params = models.JSONField(default=dict)

    # Authority at the moment of the request.
    actor_role = models.CharField(max_length=24)
    scope_kind = models.CharField(max_length=8)
    scope_ids = ArrayField(models.UUIDField(), default=list, blank=True)
    granted = ArrayField(models.CharField(max_length=40), default=list, blank=True)

    status = models.CharField(max_length=8, choices=JobStatus.choices, default=JobStatus.PENDING)
    filename = models.CharField(max_length=200, blank=True, default="")
    object_key = models.CharField(max_length=300, blank=True, default="")
    size = models.PositiveBigIntegerField(null=True, blank=True)
    sha256 = models.CharField(max_length=64, blank=True, default="")
    # Evidence packs: the digest of manifest.json, so a recipient can check what they hold.
    manifest_sha256 = models.CharField(max_length=64, blank=True, default="")
    row_count = models.PositiveIntegerField(null=True, blank=True)
    file_count = models.PositiveIntegerField(null=True, blank=True)
    error = models.CharField(max_length=300, blank=True, default="")

    requested_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    download_count = models.PositiveIntegerField(default=0)
    last_downloaded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "export_job"
        indexes = [
            models.Index(fields=["organization", "-requested_at"], name="export_org_idx"),
            models.Index(fields=["requested_by", "status"], name="export_user_active_idx"),
            models.Index(
                fields=["expires_at"],
                condition=Q(status="READY"),
                name="export_expiry_idx",
            ),
        ]
