from django.db import models
from django.db.models import Q

from .ids import uuid7


class UUIDv7Model(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)

    class Meta:
        abstract = True


class OutboxEvent(UUIDv7Model):
    """Written in the same transaction as the business change; relayed to Celery after commit."""

    topic = models.CharField(max_length=100)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "outbox_event"
        indexes = [
            models.Index(
                fields=["created_at"],
                name="outbox_unpublished_idx",
                condition=Q(published_at__isnull=True),
            )
        ]


class IdempotencyRecord(UUIDv7Model):
    """Stored outcome of a mutating request, replayed when the same key is retried."""

    user_id = models.UUIDField()
    # The operation name, so one key cannot be replayed against a different endpoint.
    scope = models.CharField(max_length=100)
    key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    response_status = models.PositiveSmallIntegerField(null=True)
    response_body = models.JSONField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "idempotency_record"
        constraints = [
            models.UniqueConstraint(
                fields=["user_id", "scope", "key"], name="idempotency_unique_key"
            )
        ]
        indexes = [models.Index(fields=["expires_at"], name="idempotency_expires_idx")]
