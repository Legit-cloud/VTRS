"""In-app notifications and their delivery tracking (FR-6.12.1, FR-6.12.2, FR-6.12.4).

A notification is one message to one user. Each channel it is sent on gets a delivery row, so
"was it sent, did it arrive, why did it fail" is a query, not a log search. In-app delivery is
the notification row itself; push, SMS, email and WhatsApp go through provider adapters.
"""

from django.db import models

from apps.core.models import UUIDv7Model


class NotificationKind(models.TextChoices):
    ANOMALY = "ANOMALY"
    ANOMALY_ESCALATED = "ANOMALY_ESCALATED"
    RESULT_REJECTED = "RESULT_REJECTED"
    RESULT_APPROVED = "RESULT_APPROVED"
    SYSTEM = "SYSTEM"


class Notification(UUIDv7Model):
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="+"
    )
    user = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=24, choices=NotificationKind.choices)
    severity = models.CharField(max_length=10, blank=True, default="")
    title = models.CharField(max_length=140)
    body = models.CharField(max_length=500)
    # Ids to open the thing this is about (flag, version, election), never figures.
    data = models.JSONField(default=dict, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notification"
        indexes = [
            models.Index(fields=["user", "-created_at"], name="notification_user_idx"),
            models.Index(
                fields=["user"],
                condition=models.Q(read_at__isnull=True),
                name="notification_unread_idx",
            ),
        ]


class DeliveryStatus(models.TextChoices):
    PENDING = "PENDING"
    SENT = "SENT"  # handed to the provider
    DELIVERED = "DELIVERED"  # the provider (or the in-app store) confirmed arrival
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"  # nothing to send to (no device, no phone) or the channel is off


class Delivery(UUIDv7Model):
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="+"
    )
    notification = models.ForeignKey(
        Notification, on_delete=models.CASCADE, related_name="deliveries"
    )
    channel = models.CharField(max_length=10)
    status = models.CharField(
        max_length=10, choices=DeliveryStatus.choices, default=DeliveryStatus.PENDING
    )
    provider_message_id = models.CharField(max_length=200, blank=True, default="")
    detail = models.CharField(max_length=200, blank=True, default="")
    attempts = models.PositiveSmallIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notification_delivery"
        constraints = [
            models.UniqueConstraint(
                fields=["notification", "channel"], name="delivery_one_per_channel"
            )
        ]
        indexes = [
            models.Index(
                fields=["status", "last_attempt_at"],
                condition=models.Q(status__in=["PENDING", "FAILED"]),
                name="delivery_open_idx",
            ),
            models.Index(
                fields=["channel", "provider_message_id"],
                condition=~models.Q(provider_message_id=""),
                name="delivery_provider_idx",
            ),
        ]
