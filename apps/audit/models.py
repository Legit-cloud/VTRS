from django.db import models
from django.utils import timezone

from apps.core.ids import uuid7
from apps.core.models import UUIDv7Model


class AuditEvent(models.Model):
    """Insert-only audit row.

    The table is created by raw SQL in the migration: it is partitioned monthly by `at`
    (primary key (id, at)), guarded by an immutability trigger, and the app role has no
    UPDATE/DELETE on it except setting `batch_id` once.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    at = models.DateTimeField()
    actor_id = models.UUIDField(null=True)
    actor_role = models.CharField(max_length=32, blank=True, default="")
    organization_id = models.UUIDField(null=True)
    action = models.CharField(max_length=100)
    object_type = models.CharField(max_length=100)
    object_id = models.CharField(max_length=64, blank=True, default="")
    ip = models.GenericIPAddressField(null=True)
    request_id = models.CharField(max_length=64, blank=True, default="")
    diff = models.JSONField(default=dict)
    batch_id = models.UUIDField(null=True)

    class Meta:
        managed = False
        db_table = "audit_event"


class AuditBatch(UUIDv7Model):
    """A sealed batch of audit events: Merkle root chained to the previous batch's root."""

    seq = models.PositiveBigIntegerField(unique=True)
    prev_root = models.CharField(max_length=64)
    merkle_root = models.CharField(max_length=64)
    root = models.CharField(max_length=64)
    event_count = models.PositiveIntegerField()
    first_event_at = models.DateTimeField()
    last_event_at = models.DateTimeField()
    sealed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "audit_batch"
