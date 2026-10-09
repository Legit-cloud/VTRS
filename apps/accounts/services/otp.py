"""OTP challenges over SMS or email (FR-6.1.2, spec section 7).

6 digits from a CSPRNG, stored as HMAC-SHA256 with a server pepper, 5-minute expiry, 5 attempts,
60-second resend cooldown, and hourly budgets per destination and per IP (anti SMS-pumping).

`verify` records failed attempts in its own savepoint and raises afterwards. Callers must not
wrap it in their own `transaction.atomic()`, or a failed attempt would be rolled back with them.
"""

import time
from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.core.crypto import blind_index
from apps.core.ids import uuid7
from apps.notifications import services as notifications

from ..domain.codes import OTP_MAX_ATTEMPTS, generate_otp, hash_otp, otp_matches
from ..domain.contact import is_allowed_sms_destination
from ..errors import OtpBudgetExceeded, OtpInvalid, OtpResendTooSoon, SmsDestinationNotAllowed
from ..models import OtpChallenge, OtpChannel, OtpPurpose

OTP_TTL = timedelta(minutes=5)
RESEND_COOLDOWN = timedelta(seconds=60)


def _pepper() -> bytes:
    return settings.VTRS_OTP_PEPPER.encode()


def _spend_budget(destination_index: str, ip: str | None) -> None:
    hour = int(time.time() // 3600)
    budgets = [(f"otp:dest:{destination_index}:{hour}", settings.VTRS_OTP_HOURLY_PER_DESTINATION)]
    if ip:
        budgets.append((f"otp:ip:{ip}:{hour}", settings.VTRS_OTP_HOURLY_PER_IP))
    for key, limit in budgets:
        cache.add(key, 0, timeout=3600)
        if cache.incr(key) > limit:
            raise OtpBudgetExceeded()


def _issue_code(challenge: OtpChallenge) -> None:
    code = generate_otp()
    now = timezone.now()
    challenge.code_hash = hash_otp(_pepper(), str(challenge.id), code)
    challenge.expires_at = now + OTP_TTL
    challenge.last_sent_at = now
    challenge.attempts = 0
    channel, destination, purpose = challenge.channel, challenge.destination, challenge.purpose
    # The plaintext code exists only in memory until the provider call after commit.
    transaction.on_commit(lambda: notifications.send_otp(channel, destination, code, purpose))


def start(
    *,
    purpose: OtpPurpose,
    channel: OtpChannel,
    destination: str,
    subject_id: UUID,
    ip: str | None,
) -> OtpChallenge:
    """Create a challenge and send its code. `destination` must already be normalized."""
    if channel == OtpChannel.SMS and not is_allowed_sms_destination(
        destination, settings.VTRS_SMS_ALLOWED_PREFIXES
    ):
        raise SmsDestinationNotAllowed()
    destination_index = blind_index(f"otp-{channel.lower()}", destination)
    _spend_budget(destination_index, ip)
    challenge = OtpChallenge(
        id=uuid7(),
        purpose=purpose,
        channel=channel,
        destination=destination,
        destination_index=destination_index,
        subject_id=subject_id,
    )
    _issue_code(challenge)
    challenge.save()
    return challenge


def resend(challenge_id: UUID, *, ip: str | None) -> None:
    """Send a fresh code. Unknown or finished challenges are ignored silently (no enumeration)."""
    with transaction.atomic():
        challenge = (
            OtpChallenge.objects.select_for_update()
            .filter(id=challenge_id, consumed_at__isnull=True)
            .first()
        )
        if challenge is None:
            return
        if timezone.now() - challenge.last_sent_at < RESEND_COOLDOWN:
            raise OtpResendTooSoon()
        _spend_budget(challenge.destination_index, ip)
        _issue_code(challenge)
        challenge.save(update_fields=["code_hash", "expires_at", "last_sent_at", "attempts"])


def peek_purpose(challenge_id: UUID) -> str | None:
    return OtpChallenge.objects.filter(id=challenge_id).values_list("purpose", flat=True).first()


def verify(challenge_id: UUID, code: str, *, purpose: OtpPurpose) -> OtpChallenge:
    """Consume the challenge if `code` matches, otherwise count the attempt and raise."""
    with transaction.atomic():
        challenge = (
            OtpChallenge.objects.select_for_update()
            .filter(id=challenge_id, purpose=purpose)
            .first()
        )
        if (
            challenge is None
            or challenge.consumed_at is not None
            or challenge.expires_at <= timezone.now()
            or challenge.attempts >= OTP_MAX_ATTEMPTS
        ):
            usable = None
        elif otp_matches(challenge.code_hash, _pepper(), str(challenge.id), code.strip()):
            challenge.consumed_at = timezone.now()
            challenge.save(update_fields=["consumed_at"])
            usable = challenge
        else:
            challenge.attempts += 1
            challenge.save(update_fields=["attempts"])
            usable = None
    if usable is None:
        raise OtpInvalid()
    return usable
