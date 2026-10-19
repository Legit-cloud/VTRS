"""Provider adapters. Real providers arrive with PB-07; until then fakes record messages."""

import base64
import hashlib
import hmac
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, Protocol

from django.conf import settings

from apps.core import http
from apps.core.logging import mask_text

logger = logging.getLogger("vtrs.notifications")


class SmsProvider(Protocol):
    def send(self, to: str, body: str) -> str:
        """Send and return the provider's message id."""
        ...


class WhatsAppProvider(Protocol):
    def send(self, to: str, body: str) -> str:
        """Send one message to a phone number and return the provider's message id."""
        ...


@dataclass(frozen=True)
class SentSms:
    to: str
    body: str


@dataclass(frozen=True)
class SentWhatsApp:
    to: str
    body: str


class FakeSmsProvider:
    """Development and test provider: keeps messages in memory and logs them masked."""

    outbox: ClassVar[list[SentSms]] = []

    def send(self, to: str, body: str) -> str:
        self.outbox.append(SentSms(to=to, body=body))
        logger.info("fake_sms_sent", extra={"to_masked": mask_text(to)})
        return f"fake-{len(self.outbox)}"


class FakeWhatsAppProvider:
    outbox: ClassVar[list[SentWhatsApp]] = []

    def send(self, to: str, body: str) -> str:
        self.outbox.append(SentWhatsApp(to, body))
        logger.info("fake_whatsapp_sent", extra={"to_masked": mask_text(to)})
        return f"fake-wa-{len(self.outbox)}"


# --- Real providers (PB-07) -----------------------------------------------------------------------
#
# Vendor-neutral where a standard exists, and the most widely used API otherwise: Twilio for SMS
# and WhatsApp. Each adapter does one request,
# raises on failure (the delivery tracker records it and retries), and never logs a message
# body or a full phone number or token.


class ProviderError(Exception):
    """The provider refused or could not accept the message."""


def twilio_signature(url: str, params: Mapping[str, str], auth_token: str) -> str:
    """The `X-Twilio-Signature` for a webhook: HMAC-SHA1 of the URL plus the sorted
    key-value pairs, base64 encoded."""
    payload = url + "".join(f"{key}{params[key]}" for key in sorted(params))
    digest = hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


class _TwilioBase:
    def __init__(self) -> None:
        self.sid = settings.VTRS_TWILIO_ACCOUNT_SID
        self.token = settings.VTRS_TWILIO_AUTH_TOKEN
        if not (self.sid and self.token):
            raise ProviderError("Twilio credentials are not configured")

    def _send(self, to: str, sender: str, body: str) -> str:
        form = {"To": to, "Body": body}
        if settings.VTRS_TWILIO_MESSAGING_SERVICE_SID and not sender.startswith("whatsapp:"):
            form["MessagingServiceSid"] = settings.VTRS_TWILIO_MESSAGING_SERVICE_SID
        else:
            form["From"] = sender
        if settings.VTRS_PUBLIC_BASE_URL:
            form["StatusCallback"] = settings.VTRS_PUBLIC_BASE_URL.rstrip("/") + (
                "/api/v1/webhooks/twilio/status"
            )
        credentials = base64.b64encode(f"{self.sid}:{self.token}".encode()).decode()
        response = http.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Messages.json",
            form=form,
            headers={"Authorization": f"Basic {credentials}"},
        )
        if not response.ok:
            code = response.json().get("code") if response.body else None
            raise ProviderError(
                f"twilio rejected the message (status {response.status}, code {code})"
            )
        message_id = response.json().get("sid", "")
        logger.info("twilio_message_accepted", extra={"to_masked": mask_text(to)})
        return str(message_id)


class TwilioSmsProvider(_TwilioBase):
    def send(self, to: str, body: str) -> str:
        return self._send(to, settings.VTRS_TWILIO_SMS_FROM, body)


class TwilioWhatsAppProvider(_TwilioBase):
    def send(self, to: str, body: str) -> str:
        number = to if to.startswith("whatsapp:") else f"whatsapp:{to}"
        return self._send(number, f"whatsapp:{settings.VTRS_TWILIO_WHATSAPP_FROM}", body)
