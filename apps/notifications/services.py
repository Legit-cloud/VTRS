"""Outbound messages (FR-6.12.x): account messages, and notifications with tracked delivery.

`send_otp` and `send_invitation` are the account messages from M1. `notify` creates an in-app
notification and a delivery row per extra channel, in the caller's transaction, and queues
delivery for after commit. `deliver` does the sending; it is idempotent, so a redelivered
event never sends a message twice (a delivery that is no longer PENDING or retryable is
skipped).
"""

import logging
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.audit import services as audit
from apps.core import rls
from apps.core import services as core
from apps.core.authz import authorize
from apps.core.domain.actor import Actor
from apps.core.domain.permissions import Perm
from apps.core.rls import system_context

from . import selectors
from .models import Delivery, DeliveryStatus, Notification

logger = logging.getLogger("vtrs.notifications")

MAX_ATTEMPTS = 3
RETRY_AFTER = timedelta(minutes=2)

IN_APP, SMS, EMAIL, WHATSAPP = "IN_APP", "SMS", "EMAIL", "WHATSAPP"

_OTP_PURPOSE_TEXT = {
    "REGISTRATION": "verify your VTRS registration",
    "PASSWORD_RESET": "reset your VTRS password",
    "INVITATION": "accept your VTRS invitation",
}


def send_sms(to: str, body: str) -> str:
    provider = import_string(settings.VTRS_SMS_PROVIDER)()
    return str(provider.send(to, body))


def send_email(to: str, subject: str, body: str) -> None:
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to])


def _deliver(channel: str, destination: str, subject: str, body: str) -> None:
    # Called after commit. A failed send must not break the request: the user can resend.
    try:
        if channel == "SMS":
            send_sms(destination, body)
        else:
            send_email(destination, subject, body)
    except Exception:
        logger.warning("notification_send_failed", exc_info=True, extra={"channel": channel})


def send_otp(channel: str, destination: str, code: str, purpose: str) -> None:
    action = _OTP_PURPOSE_TEXT.get(purpose, "continue")
    body = f"Your VTRS code is {code}. Use it to {action}. It expires in 5 minutes."
    _deliver(channel, destination, "Your VTRS verification code", body)


def send_invitation(channel: str, destination: str, link: str, organization_name: str) -> None:
    body = f"You have been invited to VTRS by {organization_name}. Open this link to accept: {link}"
    _deliver(channel, destination, "Your VTRS invitation", body)


# --- Notifications ----------------------------------------------------------------------------


def notify(
    *,
    organization_id: UUID,
    user_ids: Iterable[UUID],
    kind: str,
    title: str,
    body: str,
    severity: str = "",
    data: Mapping[str, Any] | None = None,
    channels: Iterable[str] = (IN_APP,),
) -> list[Notification]:
    """Create one notification per user with a delivery row per channel; deliver after commit.

    The in-app copy is always created: it is the record, whatever else is sent."""
    wanted = [IN_APP, *[c for c in dict.fromkeys(channels) if c != IN_APP]]
    created: list[Notification] = []
    for user_id in dict.fromkeys(user_ids):
        notification = Notification.objects.create(
            organization_id=organization_id,
            user_id=user_id,
            kind=kind,
            severity=severity,
            title=title[:140],
            body=body[:500],
            data=dict(data or {}),
        )
        now = timezone.now()
        Delivery.objects.bulk_create(
            Delivery(
                organization_id=organization_id,
                notification=notification,
                channel=channel,
                status=DeliveryStatus.DELIVERED if channel == IN_APP else DeliveryStatus.PENDING,
                delivered_at=now if channel == IN_APP else None,
            )
            for channel in wanted
        )
        created.append(notification)
    if len(wanted) > 1 and created:
        core.emit(
            "notification.created",
            {
                "organization_id": organization_id,
                "notification_ids": [n.id for n in created],
            },
        )
    return created


def _send(delivery: Delivery, user: User, notification: Notification) -> tuple[str, str]:
    """(status, provider_message_id or reason) for one channel. Raises on provider failure."""
    channel = delivery.channel
    text = f"{notification.title}: {notification.body}"
    if channel == SMS:
        if not user.phone:
            return DeliveryStatus.SKIPPED, "no_phone"
        return DeliveryStatus.SENT, send_sms(user.phone, text)
    if channel == EMAIL:
        if not user.email:
            return DeliveryStatus.SKIPPED, "no_email"
        send_email(user.email, notification.title, notification.body)
        return DeliveryStatus.SENT, ""
    if channel == WHATSAPP:
        if not settings.VTRS_FEATURE_WHATSAPP_ALERTS:
            return DeliveryStatus.SKIPPED, "channel_disabled"
        if not user.phone:
            return DeliveryStatus.SKIPPED, "no_phone"
        provider = import_string(settings.VTRS_WHATSAPP_PROVIDER)()
        return DeliveryStatus.SENT, str(provider.send(user.phone, text))
    return DeliveryStatus.SKIPPED, "unknown_channel"


def deliver(organization_id: UUID, notification_ids: Iterable[UUID]) -> int:
    """Send every pending (or retryable failed) delivery of these notifications."""
    sent = 0
    now = timezone.now()
    with transaction.atomic():
        rls.set_tenant(organization_id)
        rows = (
            Delivery.objects.select_for_update(skip_locked=True, of=("self",))
            .select_related("notification", "notification__user")
            .filter(notification_id__in=list(notification_ids))
            .filter(status__in=[DeliveryStatus.PENDING, DeliveryStatus.FAILED])
            .filter(attempts__lt=MAX_ATTEMPTS)
        )
        for delivery in rows:
            sent += _attempt(delivery, now)
    return sent


def _attempt(delivery: Delivery, now: datetime) -> int:
    notification = delivery.notification
    delivery.attempts += 1
    delivery.last_attempt_at = now
    try:
        status, info = _send(delivery, notification.user, notification)
    except Exception as exc:
        logger.warning(
            "notification_delivery_failed",
            exc_info=True,
            extra={"channel": delivery.channel, "delivery_id": str(delivery.id)},
        )
        delivery.status = DeliveryStatus.FAILED
        delivery.detail = type(exc).__name__[:200]
        delivery.save(update_fields=["status", "detail", "attempts", "last_attempt_at"])
        return 0
    delivery.status = status
    if status == DeliveryStatus.SENT:
        delivery.provider_message_id = info[:200]
        delivery.sent_at = now
    else:
        delivery.detail = info[:200]
    delivery.save(
        update_fields=[
            "status",
            "provider_message_id",
            "detail",
            "attempts",
            "last_attempt_at",
            "sent_at",
        ]
    )
    return int(status == DeliveryStatus.SENT)


def retry_failed(limit: int = 200) -> int:
    """Beat task: retry failed deliveries that still have attempts left."""
    cutoff = timezone.now() - RETRY_AFTER
    with transaction.atomic(), system_context():
        rows = list(
            Delivery.objects.filter(
                status=DeliveryStatus.FAILED,
                attempts__lt=MAX_ATTEMPTS,
                last_attempt_at__lte=cutoff,
            )
            .order_by("last_attempt_at")
            .values_list("organization_id", "notification_id")[:limit]
        )
    by_org: dict[UUID, list[UUID]] = {}
    for organization_id, notification_id in rows:
        by_org.setdefault(organization_id, []).append(notification_id)
    return sum(deliver(org, ids) for org, ids in by_org.items())


def record_receipt(
    *, channel: str, provider_message_id: str, delivered: bool, detail: str = ""
) -> bool:
    """A provider's delivery receipt: mark the matching delivery DELIVERED or FAILED."""
    with transaction.atomic(), system_context():
        delivery = Delivery.objects.filter(
            channel=channel, provider_message_id=provider_message_id
        ).first()
        if delivery is None:
            return False
        delivery.status = DeliveryStatus.DELIVERED if delivered else DeliveryStatus.FAILED
        delivery.delivered_at = timezone.now() if delivered else None
        delivery.detail = detail[:200]
        delivery.save(update_fields=["status", "delivered_at", "detail"])
        return True


# --- The user's own inbox -----------------------------------------------------------------------


def mark_read(actor: Actor, notification_id: UUID) -> Notification | None:
    notification = selectors.own_notification(actor, notification_id)
    if notification is None:
        return None
    if notification.read_at is None:
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at"])
    return notification


def mark_all_read(actor: Actor) -> int:
    return selectors.own_notifications(actor, unread=True).update(read_at=timezone.now())


def send_test_message(actor: Actor, channel: str) -> dict[str, str]:
    """Send a short message to the operator's own phone or email through the live provider.

    It goes through the same adapters as real traffic, so a failure here is a real failure.
    Only platform operators may do this, and only to their own contact details.
    """
    authorize(actor, Perm.PLATFORM_MANAGE)
    user = User.objects.get(id=actor.user_id)
    body = "VTRS test message. If you can read this, delivery is working."
    if channel == "SMS":
        if not user.phone:
            raise ValidationError({"channel": ["Your account has no phone number."]})
        destination = user.phone
        provider_id = send_sms(destination, body)
        shown = "*" * max(len(destination) - 3, 0) + destination[-3:]
    else:
        if not user.email:
            raise ValidationError({"channel": ["Your account has no email address."]})
        destination = user.email
        send_email(destination, "VTRS test message", body)
        provider_id = ""
        local, _, domain = destination.partition("@")
        shown = f"{local[:1]}***@{domain}"
    with transaction.atomic():
        audit.record(
            action="platform.messaging_test",
            object_type="user",
            object_id=actor.user_id,
            actor=actor,
            diff={"channel": channel, "provider_message_id": provider_id},
        )
    return {"sent_to": shown, "channel": channel}
