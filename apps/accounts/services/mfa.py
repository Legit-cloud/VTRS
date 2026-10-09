"""TOTP second factor with hashed single-use recovery codes (spec section 7).

Mandatory for admins and for anyone who can export; optional for other officers.
"""

import base64
import hashlib
import hmac
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.audit import services as audit
from apps.core.domain.actor import Actor

from ..domain.codes import generate_recovery_code, normalize_recovery_code
from ..errors import InvalidMfaCode, TokenRevoked
from ..models import RecoveryCode, Session, User
from .sessions import access_token_for, active_membership

RECOVERY_CODE_COUNT = 10


def _hash_recovery(code: str) -> str:
    pepper = settings.VTRS_OTP_PEPPER.encode()
    return hmac.new(pepper, normalize_recovery_code(code).encode(), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class TotpEnrolment:
    secret_base32: str
    otpauth_uri: str


def begin_totp(actor: Actor) -> TotpEnrolment:
    with transaction.atomic():
        user = User.objects.get(id=actor.user_id)
        TOTPDevice.objects.filter(user=user, confirmed=False).delete()
        device = TOTPDevice.objects.create(user=user, name="authenticator", confirmed=False)
    secret = base64.b32encode(device.bin_key).decode().rstrip("=")
    return TotpEnrolment(secret_base32=secret, otpauth_uri=device.config_url)


def _verify_totp(user: User, code: str, *, confirmed: bool) -> bool:
    devices = TOTPDevice.objects.filter(user=user, confirmed=confirmed)
    return any(device.verify_token(code.strip()) for device in devices)


def _consume_recovery_code(user: User, code: str) -> bool:
    match = RecoveryCode.objects.filter(
        user=user, code_hash=_hash_recovery(code), used_at__isnull=True
    ).first()
    if match is None:
        return False
    match.used_at = timezone.now()
    match.save(update_fields=["used_at"])
    return True


def verify_second_factor(user: User, code: str) -> bool:
    """TOTP first; recovery codes as a fallback. Failures are recorded by django-otp."""
    return _verify_totp(user, code, confirmed=True) or _consume_recovery_code(user, code)


def _mark_session_verified(actor: Actor) -> tuple[str, str]:
    if actor.session_id is None:  # only token-authenticated actors carry a session
        raise TokenRevoked()
    session = Session.objects.select_related("user").get(id=actor.session_id, user_id=actor.user_id)
    session.mfa_at = timezone.now()
    session.save(update_fields=["mfa_at"])
    membership = active_membership(actor.user_id)
    if membership is None:  # revoked between resolving the actor and now
        raise TokenRevoked()
    token, expires = access_token_for(session, membership)
    return token, expires.isoformat()


def confirm_totp(actor: Actor, code: str) -> dict[str, object]:
    """Activate the pending authenticator and hand out recovery codes (shown once)."""
    user = User.objects.get(id=actor.user_id)
    if not _verify_totp(user, code, confirmed=False):
        raise InvalidMfaCode()
    codes = [generate_recovery_code() for _ in range(RECOVERY_CODE_COUNT)]
    with transaction.atomic():
        TOTPDevice.objects.filter(user=user, confirmed=True).delete()
        TOTPDevice.objects.filter(user=user, confirmed=False).update(confirmed=True)
        RecoveryCode.objects.filter(user=user).delete()
        RecoveryCode.objects.bulk_create(
            RecoveryCode(user=user, code_hash=_hash_recovery(c)) for c in codes
        )
        User.objects.filter(id=user.id).update(mfa_enabled=True)
        token, expires = _mark_session_verified(actor)
        audit.record(action="auth.mfa_enrolled", object_type="user", object_id=user.id, actor=actor)
    return {"recovery_codes": codes, "access_token": token, "access_expires_at": expires}


def step_up(actor: Actor, code: str) -> dict[str, str]:
    """Re-confirm the second factor; returns an access token carrying a fresh mfa_at."""
    user = User.objects.get(id=actor.user_id)
    if not verify_second_factor(user, code):
        raise InvalidMfaCode()
    with transaction.atomic():
        token, expires = _mark_session_verified(actor)
        audit.record(action="auth.mfa_step_up", object_type="user", object_id=user.id, actor=actor)
    return {"access_token": token, "access_expires_at": expires}
