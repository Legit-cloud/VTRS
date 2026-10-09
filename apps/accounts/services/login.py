"""Password sign-in with progressive lockout and an optional second step (spec section 7).

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
from apps.core.crypto import blind_index
from apps.core.domain.permissions import Perm, Role, effective_permissions, requires_mfa
from apps.organizations.models import OrganizationStatus

from ..domain.contact import looks_like_email, normalize_email, normalize_phone
from ..domain.lockout import lockout_for
from ..errors import (
    AccountNotActive,
    DeviceNotRegistered,
    InvalidCredentials,
    InvalidMfaCode,
    OrganizationNotActive,
)
from ..models import Device, DeviceStatus, Membership, SessionClient, User, UserStatus
from . import mfa
from .sessions import TokenPair, active_membership, start_session

MFA_TOKEN_SALT = "vtrs.login.mfa"  # noqa: S105 - a signing namespace, not a secret
MFA_TOKEN_MAX_AGE = 300
_DUMMY_HASH = make_password("timing-equalizer-not-a-password")


@dataclass(frozen=True)
class LoginResult:
    tokens: TokenPair | None = None
    mfa_token: str | None = None
    mfa_enrolment_required: bool = False

    def as_dict(self) -> dict[str, Any]:
        if self.mfa_token:
            return {"mfa_required": True, "mfa_token": self.mfa_token}
        if self.tokens is None:
            raise RuntimeError("LoginResult has neither tokens nor an MFA token")
        return {
            "mfa_required": False,
            "mfa_enrolment_required": self.mfa_enrolment_required,
            **self.tokens.as_dict(),
        }


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


def _device_for(
    user: User, membership: Membership, client: str, device_id: UUID | None
) -> Device | None:
    if client != SessionClient.MOBILE:
        return None
    device = Device.objects.filter(user=user, status=DeviceStatus.ACTIVE).first()
    if membership.role == Role.PU_AGENT and (device is None or device.id != device_id):
        raise DeviceNotRegistered()
    return device if device is not None and device.id == device_id else None


def login(
    *, identifier: str, password: str, client: str, device_id: UUID | None, ip: str | None
) -> LoginResult:
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
    device = _device_for(user, membership, client, device_id)

    User.objects.filter(id=user.id).update(failed_login_count=0, locked_until=None)
    if user.mfa_enabled:
        token = signing.dumps(
            {"uid": str(user.id), "client": client, "device": str(device.id) if device else None},
            salt=MFA_TOKEN_SALT,
        )
        return LoginResult(mfa_token=token)

    with transaction.atomic():
        pair = start_session(
            user=user, membership=membership, client=client, device=device, mfa_at=None, ip=ip
        )
    role = Role(membership.role)
    granted = [Perm(p) for p in membership.granted_permissions if p in Perm._value2member_map_]
    needs_mfa = requires_mfa(role, effective_permissions(role, granted))
    return LoginResult(tokens=pair, mfa_enrolment_required=needs_mfa)


def complete_mfa(*, mfa_token: str, code: str, ip: str | None) -> TokenPair:
    try:
        data = signing.loads(mfa_token, salt=MFA_TOKEN_SALT, max_age=MFA_TOKEN_MAX_AGE)
    except signing.BadSignature:
        raise InvalidMfaCode() from None
    user = User.objects.filter(id=data["uid"], status=UserStatus.ACTIVE).first()
    membership = active_membership(user.id) if user else None
    if user is None or membership is None:
        raise InvalidMfaCode()
    if not mfa.verify_second_factor(user, code):
        raise InvalidMfaCode()
    device = Device.objects.filter(id=data["device"]).first() if data["device"] else None
    with transaction.atomic():
        return start_session(
            user=user,
            membership=membership,
            client=data["client"],
            device=device,
            mfa_at=timezone.now(),
            ip=ip,
        )
