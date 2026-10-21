"""Second factor: a one-time code sent to the account's email address (spec section 7).

Every role enters a code at sign-in, and sensitive actions ask for a fresh one (step-up). The
codes are ordinary OTP challenges (`otp`): 6 digits, 5 minutes, 5 attempts, resend cooldown and
hourly budgets. There is no authenticator app and there are no recovery codes.
"""

from dataclasses import dataclass
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.core.domain.actor import Actor

from ..domain.contact import mask_email
from ..errors import InvalidMfaCode, OtpInvalid, SignInEmailMissing, TokenRevoked
from ..models import OtpChallenge, OtpChannel, OtpPurpose, Session, User
from . import otp
from .sessions import access_token_for, active_membership


@dataclass(frozen=True)
class CodeSent:
    challenge_id: UUID
    destination_hint: str


def send_code(user: User, purpose: OtpPurpose, *, ip: str | None) -> CodeSent:
    """Email a code, or hand back the one sent moments ago (a double submit sends one email)."""
    if not user.email:
        raise SignInEmailMissing()
    hint = mask_email(user.email)
    recent = (
        OtpChallenge.objects.filter(
            subject_id=user.id,
            purpose=purpose,
            consumed_at__isnull=True,
            last_sent_at__gt=timezone.now() - otp.RESEND_COOLDOWN,
        )
        .order_by("-last_sent_at")
        .first()
    )
    if recent is not None:
        return CodeSent(recent.id, hint)
    challenge = otp.start(
        purpose=purpose,
        channel=OtpChannel.EMAIL,
        destination=user.email,
        subject_id=user.id,
        ip=ip,
    )
    return CodeSent(challenge.id, hint)


def verify_code(user: User, challenge_id: UUID, code: str, purpose: OtpPurpose) -> None:
    """Consume the challenge if it is this user's and the code matches. Not inside atomic()."""
    try:
        challenge = otp.verify(challenge_id, code, purpose=purpose)
    except OtpInvalid:
        raise InvalidMfaCode() from None
    if challenge.subject_id != user.id:
        raise InvalidMfaCode()


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


def request_step_up(actor: Actor, *, ip: str | None) -> CodeSent:
    return send_code(User.objects.get(id=actor.user_id), OtpPurpose.STEP_UP, ip=ip)


def step_up(actor: Actor, challenge_id: UUID, code: str) -> dict[str, str]:
    """Re-confirm the second factor; returns an access token carrying a fresh mfa_at."""
    user = User.objects.get(id=actor.user_id)
    verify_code(user, challenge_id, code, OtpPurpose.STEP_UP)
    with transaction.atomic():
        token, expires = _mark_session_verified(actor)
        audit.record(action="auth.mfa_step_up", object_type="user", object_id=user.id, actor=actor)
    return {"access_token": token, "access_expires_at": expires}
