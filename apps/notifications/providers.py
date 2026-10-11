"""Provider adapters. Real providers arrive with PB-07; until then fakes record messages."""

import logging
from dataclasses import dataclass
from typing import ClassVar, Protocol

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
