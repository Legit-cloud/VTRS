"""Password sign-in with progressive lockout, then a code by email (spec section 7).

Unknown accounts, wrong passwords and locked accounts all get the same error. Counters and
audit rows are written before the error is raised, so they survive the failed request.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.contrib.auth.hashers import check_password, make_password
from django.core import signing
from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.core.authz import mfa_mandatory
from apps.core.crypto import blind_index
from apps.organizations.models import OrganizationStatus

from ..domain.contact import looks_like_email, normalize_email, normalize_phone
from ..domain.lockout import lockout_for
from ..errors import (
    AccountNotActive,
    InvalidCredentials,
    InvalidMfaCode,
    OrganizationNotActive,
)
from ..models import OtpPurpose, User, UserStatus
from . import mfa, otp
from .sessions import TokenPair, active_membership, start_session

MFA_TOKEN_SALT = "vtrs.login.mfa"  # noqa: S105 - a signing namespace, not a secret
MFA_TOKEN_MAX_AGE = 300
_DUMMY_HASH = make_password("timing-equalizer-not-a-password")


@dataclass(frozen=True)
class LoginResult:
    tokens: TokenPair | None = None
    mfa_token: str | None = None
    code: mfa.CodeSent | None = None

    def as_dict(self) -> dict[str, Any]:
        if self.mfa_token and self.code:
            return {
                "mfa_required": True,
                "mfa_token": self.mfa_token,
                "challenge_id": self.code.challenge_id,
                "destination_hint": self.code.destination_hint,
            }
        if self.tokens is None:
            raise RuntimeError("LoginResult has neither tokens nor an MFA token")
        return {"mfa_required": False, **self.tokens.as_dict()}


def find_user(identifier: str) -> User | None:
    try:
        if looks_like_email(identifier):
            index = ("email_index", blind_index("email", normalize_email(identifier)))
        else:
            index = ("phone_index", blind_index("phone", normalize_phone(identifier)))
    except ValueError:
        return None
    return User.objects.filter(**{index[0]: index[1]}).first()


def _check_password(user: User | None, password: str) -> bool:
    if user is None:
        # Hash anyway so unknown accounts take as long as known ones.
        check_password(password, _DUMMY_HASH)
        return False
    return user.check_password(password)


def _record_failure(user: User | None, ip: str | None) -> None:
    with transaction.atomic():
        if user is not None:
            locked = User.objects.select_for_update().get(id=user.id)
            locked.failed_login_count += 1
            duration = lockout_for(locked.failed_login_count)
            if duration:
                locked.locked_until = timezone.now() + duration
            locked.save(update_fields=["failed_login_count", "locked_until"])
        audit.record(
            action="auth.sign_in_failed",
            object_type="user",
            object_id=user.id if user else "",
            diff={"ip_only": user is None},
        )


def login(*, identifier: str, password: str, ip: str | None) -> LoginResult:
    user = find_user(identifier)
    now = timezone.now()
    if user is not None and user.locked_until and user.locked_until > now:
        raise InvalidCredentials()
    if not _check_password(user, password):
        _record_failure(user, ip)
        raise InvalidCredentials()
    if user is None:  # unreachable: _check_password fails for unknown users
        raise InvalidCredentials()

    if user.status != UserStatus.ACTIVE:
        raise AccountNotActive()
    membership = active_membership(user.id)
    if membership is None:
        raise AccountNotActive()
    if membership.organization.status != OrganizationStatus.ACTIVE:
        raise OrganizationNotActive()

    User.objects.filter(id=user.id).update(failed_login_count=0, locked_until=None)
    if mfa_mandatory():
        sent = mfa.send_code(user, OtpPurpose.SIGN_IN, ip=ip)
        token = signing.dumps(
            {"uid": str(user.id), "cid": str(sent.challenge_id)}, salt=MFA_TOKEN_SALT
        )
        return LoginResult(mfa_token=token, code=sent)

    # Development settings may turn the code off; the session then has no second factor.
    with transaction.atomic():
        pair = start_session(user=user, membership=membership, mfa_at=None, ip=ip)
    return LoginResult(tokens=pair)


def _pending(mfa_token: str) -> tuple[User, UUID]:
    try:
        data = signing.loads(mfa_token, salt=MFA_TOKEN_SALT, max_age=MFA_TOKEN_MAX_AGE)
        challenge_id = UUID(data["cid"])
    except (signing.BadSignature, KeyError, ValueError):
        raise InvalidMfaCode() from None
    user = User.objects.filter(id=data["uid"], status=UserStatus.ACTIVE).first()
    if user is None:
        raise InvalidMfaCode()
    return user, challenge_id


def resend_code(*, mfa_token: str, ip: str | None) -> None:
    """Send a fresh sign-in code (60-second cooldown, hourly budgets)."""
    _, challenge_id = _pending(mfa_token)
    otp.resend(challenge_id, ip=ip)


def complete_mfa(*, mfa_token: str, code: str, ip: str | None) -> TokenPair:
    user, challenge_id = _pending(mfa_token)
    if active_membership(user.id) is None:
        raise InvalidMfaCode()
    mfa.verify_code(user, challenge_id, code, OtpPurpose.SIGN_IN)
    membership = active_membership(user.id)
    if membership is None:  # revoked while the code was in flight
        raise InvalidMfaCode()
    with transaction.atomic():
        return start_session(user=user, membership=membership, mfa_at=timezone.now(), ip=ip)
