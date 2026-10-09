"""Team management (FR-6.11.1 - FR-6.11.4): deactivate users, change role/scope, revoke devices.

Role and scope changes need a fresh second factor, take effect on the very next request
(the actor is rebuilt from the membership each time), and are audited with before/after.
The last active admin of an organization can be neither deactivated nor demoted.
"""

from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.audit import services as audit
from apps.core.authz import authorize, require_recent_mfa
from apps.core.domain.actor import Actor
from apps.core.domain.permissions import Perm, Role

from ..errors import LastAdmin
from ..models import Device, DeviceStatus, Membership, MembershipStatus, User, UserStatus
from .invitations import validate_grant
from .sessions import revoke_all_sessions, revoke_session


def _ensure_not_last_admin(membership: Membership) -> None:
    if membership.role != Role.PARTY_ADMIN:
        return
    others = (
        Membership.objects.filter(
            organization_id=membership.organization_id,
            role=Role.PARTY_ADMIN,
            status=MembershipStatus.ACTIVE,
            user__status=UserStatus.ACTIVE,
        )
        .exclude(id=membership.id)
        .exists()
    )
    if not others:
        raise LastAdmin()


def _snapshot(membership: Membership) -> dict[str, Any]:
    return {
        "role": membership.role,
        "scope_type": membership.scope_type,
        "scope_ids": sorted(str(i) for i in membership.scope_ids),
        "granted_permissions": sorted(membership.granted_permissions),
    }


def deactivate_user(actor: Actor, membership: Membership) -> User:
    authorize(actor, Perm.USERS_MANAGE)
    with transaction.atomic():
        membership = Membership.objects.select_for_update().get(id=membership.id)
        _ensure_not_last_admin(membership)
        user = User.objects.select_for_update().get(id=membership.user_id)
        if user.status == UserStatus.DEACTIVATED:
            return user
        user.status = UserStatus.DEACTIVATED
        user.save(update_fields=["status"])
        revoked = revoke_all_sessions(user, "deactivated")
        Device.objects.filter(user=user, status=DeviceStatus.ACTIVE).update(
            status=DeviceStatus.REVOKED, revoked_at=timezone.now()
        )
        audit.record(
            action="user.deactivated",
            object_type="user",
            object_id=user.id,
            actor=actor,
            diff={"sessions_revoked": revoked},
        )
    return user


def update_membership(
    actor: Actor,
    membership: Membership,
    *,
    role: str,
    scope_ids: list[UUID],
    granted_permissions: list[str],
) -> Membership:
    authorize(actor, Perm.USERS_MANAGE)
    require_recent_mfa(actor)
    new_role = Role(role)
    kind, scope_ids, granted = validate_grant(actor, new_role, scope_ids, granted_permissions)
    with transaction.atomic():
        membership = Membership.objects.select_for_update().get(id=membership.id)
        before = _snapshot(membership)
        if new_role != membership.role:
            _ensure_not_last_admin(membership)
        membership.role = new_role
        membership.scope_type = kind
        membership.scope_ids = scope_ids
        membership.granted_permissions = granted
        membership.save(
            update_fields=["role", "scope_type", "scope_ids", "granted_permissions", "updated_at"]
        )
        User.objects.filter(id=membership.user_id).update(scope_version=F("scope_version") + 1)
        audit.record(
            action="user.membership_changed",
            object_type="user",
            object_id=membership.user_id,
            actor=actor,
            diff={"before": before, "after": _snapshot(membership)},
        )
    return membership


def revoke_device(actor: Actor, membership: Membership, device_id: UUID) -> Device | None:
    authorize(actor, Perm.USERS_MANAGE)
    with transaction.atomic():
        device = (
            Device.objects.select_for_update()
            .filter(id=device_id, user_id=membership.user_id)
            .first()
        )
        if device is None:
            return None
        if device.status == DeviceStatus.ACTIVE:
            device.status = DeviceStatus.REVOKED
            device.revoked_at = timezone.now()
            device.save(update_fields=["status", "revoked_at"])
            # Sessions bound to the device end with it.
            for session in device.session_set.filter(revoked_at__isnull=True):
                revoke_session(session, "device_revoked")
            audit.record(
                action="device.revoked",
                object_type="device",
                object_id=device.id,
                actor=actor,
                diff={"user_id": membership.user_id},
            )
    return device
