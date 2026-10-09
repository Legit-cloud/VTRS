"""Password recovery: OTP-verified, single-use 15-minute reset token stored hashed (section 7).

Never reveals whether an account exists: unknown identifiers get a decoy challenge id.
"""

from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.core.ids import uuid7

from ..domain.codes import generate_token, hash_token
from ..domain.contact import looks_like_email
from ..errors import InvalidResetToken
from ..models import OtpChannel, OtpPurpose, PasswordResetToken, UserStatus
from . import otp
from .login import find_user
from .registration import check_password_strength
from .sessions import revoke_all_sessions

RESET_TOKEN_TTL = timedelta(minutes=15)


def request_reset(identifier: str, *, ip: str | None) -> UUID:
    user = find_user(identifier)
    if user is None or user.status != UserStatus.ACTIVE:
        return uuid7()
    channel = OtpChannel.EMAIL if looks_like_email(identifier) else OtpChannel.SMS
    destination = user.email if channel == OtpChannel.EMAIL else user.phone
    with transaction.atomic():
        challenge = otp.start(
            purpose=OtpPurpose.PASSWORD_RESET,
            channel=channel,
            destination=destination,
            subject_id=user.id,
            ip=ip,
        )
    return challenge.id


def issue_reset_token(challenge_id: UUID, code: str) -> str:
    challenge = otp.verify(challenge_id, code, purpose=OtpPurpose.PASSWORD_RESET)
    token = generate_token()
    PasswordResetToken.objects.create(
        user_id=challenge.subject_id,
        token_hash=hash_token(token),
        expires_at=timezone.now() + RESET_TOKEN_TTL,
    )
    return token


def reset_password(reset_token: str, new_password: str) -> None:
    with transaction.atomic():
        record = (
            PasswordResetToken.objects.select_for_update()
            .select_related("user")
            .filter(token_hash=hash_token(reset_token), used_at__isnull=True)
            .first()
        )
        if record is None or record.expires_at <= timezone.now():
            raise InvalidResetToken()
        user = record.user
        check_password_strength(new_password, user)
        user.set_password(new_password)
        user.failed_login_count = 0
        user.locked_until = None
        user.save(update_fields=["password", "failed_login_count", "locked_until"])
        record.used_at = timezone.now()
        record.save(update_fields=["used_at"])
        revoke_all_sessions(user, "password_reset")
        audit.record(action="auth.password_reset", object_type="user", object_id=user.id)
