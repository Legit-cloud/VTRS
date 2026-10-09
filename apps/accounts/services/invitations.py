"""Invite-only onboarding (FR-6.1.5, FR-6.2.1 - FR-6.2.4, AC-03).

Admin invites with role, scope and contact -> a 256-bit token goes out by SMS/email (only its
hash is stored) -> the invitee presents the token and gets an OTP on the *invited* contact ->
with the code they set a password (agents also register their device) -> the account is
ACTIVE and signed in. Used, expired, revoked and unknown tokens all fail the same way.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.core.authz import authorize
from apps.core.crypto import blind_index
from apps.core.domain.actor import ROLE_SCOPE_KIND, Actor, ScopeKind
from apps.core.domain.permissions import GRANTABLE_PERMISSIONS, Perm, Role, can_assign_role
from apps.core.errors import Forbidden
from apps.core.rls import system_context
from apps.geography import selectors as geography
from apps.notifications import services as notifications

from ..domain.codes import generate_token, hash_token
from ..domain.contact import mask_email, mask_phone
from ..errors import ContactInUse, InvitationInvalid
from ..models import (
    Device,
    Invitation,
    Membership,
    OtpChannel,
    OtpPurpose,
    SessionClient,
    User,
    UserStatus,
)
from . import otp
from .registration import check_password_strength, normalized_contact
from .sessions import TokenPair, start_session


def validate_grant(
    actor: Actor, role: Role, scope_ids: list[UUID], granted: list[str]
) -> tuple[ScopeKind, list[UUID], list[str]]:
    """Privilege rules (section 8): roles at or below your own, scopes inside your own."""
    if not can_assign_role(actor.role, role):
        raise Forbidden("You cannot grant a role above your own.")
    if actor.scope.kind is not ScopeKind.ORG:
        # Only organization-wide users hold users.manage today, so narrower granters never
        # reach this point. Supporting them needs a hierarchy containment check first.
        raise Forbidden("Only organization-wide users can grant scopes.")
    kind = ROLE_SCOPE_KIND[role]
    if kind is ScopeKind.ORG:
        if scope_ids:
            raise ValidationError({"scope_ids": ["An organization-wide role takes no scope ids."]})
    else:
        if not scope_ids:
            raise ValidationError({"scope_ids": [f"A {role} needs at least one {kind} id."]})
        missing = geography.missing_ids(actor, kind, scope_ids)
        if missing:
            raise ValidationError(
                {"scope_ids": [f"Unknown {kind} ids: {sorted(map(str, missing))}"]}
            )
    allowed = {p.value for p in GRANTABLE_PERMISSIONS[role]}
    rejected = sorted(set(granted) - allowed)
    if rejected:
        raise ValidationError({"granted_permissions": [f"Not grantable to {role}: {rejected}"]})
    return kind, sorted(set(scope_ids)), sorted(set(granted))


def _contact_in_use(email_index: str | None, phone_index: str | None) -> bool:
    with system_context():
        return (
            email_index is not None and User.objects.filter(email_index=email_index).exists()
        ) or (phone_index is not None and User.objects.filter(phone_index=phone_index).exists())


def create_invitation(
    actor: Actor,
    *,
    role: str,
    scope_ids: list[UUID],
    granted_permissions: list[str],
    full_name: str,
    email: str,
    phone: str,
) -> Invitation:
    authorize(actor, Perm.USERS_MANAGE)
    role_enum = Role(role)
    kind, scope_ids, granted = validate_grant(actor, role_enum, scope_ids, granted_permissions)
    email, phone = normalized_contact(email, phone)
    if role_enum is Role.PU_AGENT and not phone:
        raise ValidationError({"phone": ["Agents are invited by phone."]})
    if not email and not phone:
        raise ValidationError({"phone": ["Give a phone number or an email address."]})
    email_index = blind_index("email", email) if email else None
    phone_index = blind_index("phone", phone) if phone else None
    if _contact_in_use(email_index, phone_index):
        raise ContactInUse()

    token = generate_token()
    with transaction.atomic():
        invitation = Invitation.objects.create(
            organization_id=actor.organization_id,
            role=role_enum,
            scope_type=kind,
            scope_ids=scope_ids,
            granted_permissions=granted,
            full_name=full_name,
            email=email,
            email_index=email_index,
            phone=phone,
            phone_index=phone_index,
            token_hash=hash_token(token),
            expires_at=timezone.now() + timedelta(hours=settings.VTRS_INVITATION_TTL_HOURS),
            created_by_id=actor.user_id,
        )
        audit.record(
            action="invitation.created",
            object_type="invitation",
            object_id=invitation.id,
            actor=actor,
            diff={
                "role": role_enum,
                "scope_type": kind,
                "scope_ids": scope_ids,
                "granted": granted,
            },
        )
        channel, destination = ("SMS", phone) if phone else ("EMAIL", email)
        link = settings.VTRS_INVITATION_LINK.format(token=token)
        org_name = invitation.organization.name
        transaction.on_commit(
            lambda: notifications.send_invitation(channel, destination, link, org_name)
        )
    return invitation


def revoke_invitation(actor: Actor, invitation: Invitation) -> Invitation:
    authorize(actor, Perm.USERS_MANAGE)
    with transaction.atomic():
        if invitation.accepted_at is None and invitation.revoked_at is None:
            invitation.revoked_at = timezone.now()
            invitation.save(update_fields=["revoked_at"])
            audit.record(
                action="invitation.revoked",
                object_type="invitation",
                object_id=invitation.id,
                actor=actor,
            )
    return invitation


def _usable(token: str, *, lock: bool = False) -> Invitation:
    qs = Invitation.objects.select_related("organization")
    if lock:
        qs = qs.select_for_update(of=("self",))
    invitation = qs.filter(token_hash=hash_token(token)).first()
    if (
        invitation is None
        or invitation.accepted_at is not None
        or invitation.revoked_at is not None
        or invitation.expires_at <= timezone.now()
    ):
        raise InvitationInvalid()
    return invitation


@dataclass(frozen=True)
class AcceptanceStarted:
    challenge_id: UUID
    channel: str
    destination_hint: str


def start_acceptance(token: str, *, ip: str | None) -> AcceptanceStarted:
    with transaction.atomic(), system_context():
        invitation = _usable(token)
        channel = OtpChannel.SMS if invitation.phone else OtpChannel.EMAIL
        destination = invitation.phone or invitation.email
        challenge = otp.start(
            purpose=OtpPurpose.INVITATION,
            channel=channel,
            destination=destination,
            subject_id=invitation.id,
            ip=ip,
        )
    hint = mask_phone(destination) if channel == OtpChannel.SMS else mask_email(destination)
    return AcceptanceStarted(challenge.id, channel, hint)


@dataclass(frozen=True)
class AcceptanceResult:
    user: User
    membership: Membership
    tokens: TokenPair


def complete_acceptance(
    *,
    token: str,
    challenge_id: UUID,
    code: str,
    password: str,
    device: dict[str, Any] | None,
    ip: str | None,
) -> AcceptanceResult:
    with transaction.atomic(), system_context():
        invitation_id = _usable(token).id
    challenge = otp.verify(challenge_id, code, purpose=OtpPurpose.INVITATION)
    if challenge.subject_id != invitation_id:
        raise InvitationInvalid()
    check_password_strength(password)

    with transaction.atomic(), system_context():
        invitation = _usable(token, lock=True)
        role = Role(invitation.role)
        if role is Role.PU_AGENT and not device:
            raise ValidationError({"device": ["Agents must register their device."]})
        if _contact_in_use(invitation.email_index, invitation.phone_index):
            raise ContactInUse()
        now = timezone.now()
        user = User.objects.create_user(
            password=password,
            full_name=invitation.full_name,
            email=invitation.email,
            email_index=invitation.email_index,
            phone=invitation.phone,
            phone_index=invitation.phone_index,
            phone_verified_at=now if challenge.channel == OtpChannel.SMS else None,
            email_verified_at=now if challenge.channel == OtpChannel.EMAIL else None,
            status=UserStatus.ACTIVE,
        )
        membership = Membership.objects.create(
            user=user,
            organization_id=invitation.organization_id,
            role=role,
            scope_type=invitation.scope_type,
            scope_ids=invitation.scope_ids,
            granted_permissions=invitation.granted_permissions,
            created_by_id=invitation.created_by_id,
        )
        registered = Device.objects.create(user=user, **device) if device else None
        invitation.accepted_at = now
        invitation.accepted_user_id = user.id
        invitation.save(update_fields=["accepted_at", "accepted_user_id"])
        audit.record(
            action="invitation.accepted",
            object_type="invitation",
            object_id=invitation.id,
            organization_id=invitation.organization_id,
            diff={"user_id": user.id, "device_id": registered.id if registered else None},
        )
        membership.user = user
        pair = start_session(
            user=user,
            membership=membership,
            client=SessionClient.MOBILE if registered else SessionClient.WEB,
            device=registered,
            mfa_at=None,
            ip=ip,
        )
    return AcceptanceResult(user=user, membership=membership, tokens=pair)
