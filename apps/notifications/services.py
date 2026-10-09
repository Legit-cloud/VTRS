"""Outbound account messages (FR-6.12.2). Delivery tracking and push arrive with M5."""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.utils.module_loading import import_string

logger = logging.getLogger("vtrs.notifications")

_OTP_PURPOSE_TEXT = {
    "REGISTRATION": "verify your VTRS registration",
    "PASSWORD_RESET": "reset your VTRS password",
    "INVITATION": "accept your VTRS invitation",
}


def send_sms(to: str, body: str) -> None:
    provider = import_string(settings.VTRS_SMS_PROVIDER)()
    provider.send(to, body)


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
