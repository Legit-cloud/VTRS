"""SMS provider adapters. Real providers arrive with PB-07; until then a fake records messages."""

import logging
from dataclasses import dataclass
from typing import ClassVar, Protocol

from apps.core.logging import mask_text

logger = logging.getLogger("vtrs.notifications")


class SmsProvider(Protocol):
    def send(self, to: str, body: str) -> str:
        """Send and return the provider's message id."""
        ...


@dataclass(frozen=True)
class SentSms:
    to: str
    body: str


class FakeSmsProvider:
    """Development and test provider: keeps messages in memory and logs them masked."""

    outbox: ClassVar[list[SentSms]] = []

    def send(self, to: str, body: str) -> str:
        self.outbox.append(SentSms(to=to, body=body))
        logger.info("fake_sms_sent", extra={"to_masked": mask_text(to)})
        return f"fake-{len(self.outbox)}"
