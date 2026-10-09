from django.db import models
from django.db.models import Q

from apps.core.ids import uuid7
from apps.core.scope import ScopedQuerySet

from .domain.rules import EvidenceKind, EvidenceStatus


def _choices(enum: type[EvidenceKind] | type[EvidenceStatus]) -> list[tuple[str, str]]:
    return [(member.value, member.value) for member in enum]


class EvidenceFile(models.Model):
    """A result-sheet image. Bytes live in private object storage; this row is the record."""

    SCOPE_LOOKUPS = {
        "org": "organization_id",
        "lga": "lga_id",
        "ward": "ward_id",
        "pu": "polling_unit_id",
    }

    # Client-generated evidence id, so retries of the same photo are idempotent.
    id = models.UUIDField(primary_key=True, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="+"
    )
    result_version = models.ForeignKey(
        "results.ResultVersion", on_delete=models.PROTECT, related_name="evidence"
    )
    polling_unit = models.ForeignKey(
        "geography.PollingUnit", on_delete=models.PROTECT, related_name="+"
    )
    ward = models.ForeignKey("geography.Ward", on_delete=models.PROTECT, related_name="+")
    lga = models.ForeignKey("geography.Lga", on_delete=models.PROTECT, related_name="+")
    uploaded_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=8, choices=_choices(EvidenceKind))
    object_key = models.CharField(max_length=300, unique=True)
    size = models.PositiveIntegerField()
    mime = models.CharField(max_length=20)
    sha256_client = models.CharField(max_length=64)
    sha256_server = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(
        max_length=16, choices=_choices(EvidenceStatus), default=EvidenceStatus.PENDING_UPLOAD
    )
    quarantine_reason = models.CharField(max_length=200, blank=True, default="")
    # EXIF capture time and GPS, perceptual hash, derived object keys (for anomaly rules).
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    uploaded_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    objects = ScopedQuerySet.as_manager()

    class Meta:
        db_table = "evidence_file"
        indexes = [
            models.Index(
                fields=["created_at"],
                condition=Q(status="PENDING_UPLOAD"),
                name="evidence_pending_idx",
            ),
            models.Index(fields=["uploaded_by", "created_at"], name="evidence_uploader_idx"),
        ]


class CustodyEvent(models.Model):
    """Append-only, hash-chained per file; partitioned monthly by `at` (created in SQL)."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    at = models.DateTimeField()
    organization_id = models.UUIDField()
    evidence_file_id = models.UUIDField()
    seq = models.PositiveIntegerField()
    event_type = models.CharField(max_length=40)
    actor_id = models.UUIDField(null=True)
    ip = models.GenericIPAddressField(null=True)
    details = models.JSONField(default=dict)
    prev_hash = models.CharField(max_length=64)
    hash = models.CharField(max_length=64)

    class Meta:
        managed = False
        db_table = "custody_event"
