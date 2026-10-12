"""Provider adapters. Real providers arrive with PB-07; until then fakes record messages."""

import base64
import hashlib
import hmac
import json
import logging
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, Protocol

import jwt
from django.conf import settings

from apps.core import http
from apps.core.logging import mask_text

logger = logging.getLogger("vtrs.notifications")


class SmsProvider(Protocol):
    def send(self, to: str, body: str) -> str:
        """Send and return the provider's message id."""
        ...


class PushProvider(Protocol):
    def send(self, token: str, title: str, body: str, data: dict[str, str]) -> str:
        """Send to one device token and return the provider's message id."""
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
class SentPush:
    token: str
    title: str
    body: str
    data: dict[str, str]


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


class FakePushProvider:
    """Development and test provider. Real push (FCM) arrives with PB-07."""

    outbox: ClassVar[list[SentPush]] = []

    def send(self, token: str, title: str, body: str, data: dict[str, str]) -> str:
        self.outbox.append(SentPush(token, title, body, data))
        logger.info("fake_push_sent", extra={"token_masked": mask_text(token)})
        return f"fake-push-{len(self.outbox)}"


class FakeWhatsAppProvider:
    outbox: ClassVar[list[SentWhatsApp]] = []

    def send(self, to: str, body: str) -> str:
        self.outbox.append(SentWhatsApp(to, body))
        logger.info("fake_whatsapp_sent", extra={"to_masked": mask_text(to)})
        return f"fake-wa-{len(self.outbox)}"


# --- Real providers (PB-07) -----------------------------------------------------------------------
#
# Vendor-neutral where a standard exists, and the most widely used API otherwise: Twilio for SMS
# and WhatsApp, Firebase Cloud Messaging HTTP v1 for push. Each adapter does one request,
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


_FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_token_lock = threading.Lock()
_token_cache: dict[str, tuple[str, float]] = {}


class FcmPushProvider:
    """Firebase Cloud Messaging HTTP v1, authenticated with a service account."""

    def __init__(self) -> None:
        raw = settings.VTRS_FCM_SERVICE_ACCOUNT_JSON
        if not raw:
            raise ProviderError("FCM service account is not configured")
        try:
            self.account = json.loads(raw)
            self.project = self.account["project_id"]
        except (ValueError, KeyError) as exc:
            raise ProviderError("FCM service account is malformed") from exc

    def _access_token(self) -> str:
        with _token_lock:
            cached = _token_cache.get(self.project)
            if cached and cached[1] > time.time() + 60:
                return cached[0]
            now = int(time.time())
            assertion = jwt.encode(
                {
                    "iss": self.account["client_email"],
                    "scope": _FCM_SCOPE,
                    "aud": self.account.get("token_uri", "https://oauth2.googleapis.com/token"),
                    "iat": now,
                    "exp": now + 3600,
                },
                self.account["private_key"],
                algorithm="RS256",
            )
            response = http.post(
                self.account.get("token_uri", "https://oauth2.googleapis.com/token"),
                form={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
            )
            if not response.ok:
                raise ProviderError(f"FCM token exchange failed (status {response.status})")
            payload = response.json()
            token = str(payload["access_token"])
            _token_cache[self.project] = (token, now + int(payload.get("expires_in", 3600)))
            return token

    def send(self, token: str, title: str, body: str, data: dict[str, str]) -> str:
        response = http.post(
            f"https://fcm.googleapis.com/v1/projects/{self.project}/messages:send",
            json_body={
                "message": {
                    "token": token,
                    "notification": {"title": title, "body": body},
                    "data": data,
                    "android": {"priority": "HIGH"},
                }
            },
            headers={"Authorization": f"Bearer {self._access_token()}"},
        )
        if not response.ok:
            status = response.json().get("error", {}).get("status", "") if response.body else ""
            raise ProviderError(f"FCM rejected the push (status {response.status} {status})")
        logger.info("fcm_push_accepted", extra={"token_masked": mask_text(token)})
        return str(response.json().get("name", ""))
