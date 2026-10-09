"""Sessions, token issue and rotation, revocation, and per-request actor resolution (section 7).

- Access token: 10-minute EdDSA JWT.
- Refresh token: opaque 256-bit, stored hashed, rotated on every use. Presenting a used token
  again revokes the whole session (reuse detection).
- Mobile sessions slide (7 days from last refresh) and are bound to the registered device.
  Web sessions end 12 hours after sign-in, whatever happens.
- Emergency revocation: bump the user's session_version and deny-list the session id for the
  access-token lifetime.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.core.domain.actor import Actor, Scope, ScopeKind
from apps.core.domain.permissions import Perm, Role
from apps.core.rls import system_context
from apps.organizations.models import OrganizationStatus

from .. import tokens
from ..domain.codes import generate_token, hash_token
from ..errors import InvalidRefreshToken, TokenRevoked
from ..models import (
    Device,
    Membership,
    MembershipStatus,
    RefreshToken,
    Session,
    SessionClient,
    User,
    UserStatus,
)

_DENY_PREFIX = "session-denied:"


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime
    session_id: UUID

    def as_dict(self) -> dict[str, str]:
        return {
            "token_type": "Bearer",
            "access_token": self.access_token,
            "access_expires_at": self.access_expires_at.isoformat(),
            "refresh_token": self.refresh_token,
            "refresh_expires_at": self.refresh_expires_at.isoformat(),
            "session_id": str(self.session_id),
        }


def _session_lifetime(client: str) -> timedelta:
    if client == SessionClient.MOBILE:
        return timedelta(days=settings.VTRS_MOBILE_SESSION_DAYS)
    return timedelta(hours=settings.VTRS_WEB_SESSION_HOURS)


def _new_refresh_token(session: Session) -> str:
    token = generate_token()
    RefreshToken.objects.create(session=session, token_hash=hash_token(token))
    return token


def access_token_for(session: Session, membership: Membership) -> tuple[str, datetime]:
    return tokens.issue_access_token(
        user_id=session.user_id,
        organization_id=membership.organization_id,
        session_id=session.id,
        session_version=session.user.session_version,
        mfa_at=session.mfa_at,
    )


def start_session(
    *,
    user: User,
    membership: Membership,
    client: str,
    device: Device | None,
    mfa_at: datetime | None,
    ip: str | None,
) -> TokenPair:
    now = timezone.now()
    session = Session.objects.create(
        user=user,
        device=device,
        client=client,
        expires_at=now + _session_lifetime(client),
        last_used_at=now,
        mfa_at=mfa_at,
        ip=ip,
    )
    refresh = _new_refresh_token(session)
    access, access_expires = access_token_for(session, membership)
    audit.record(
        action="auth.signed_in",
        object_type="session",
        object_id=session.id,
        organization_id=membership.organization_id,
        diff={"user_id": user.id, "client": client, "mfa": mfa_at is not None},
    )
    return TokenPair(access, access_expires, refresh, session.expires_at, session.id)


def _deny(session_id: UUID) -> None:
    cache.set(f"{_DENY_PREFIX}{session_id}", True, timeout=settings.VTRS_ACCESS_TOKEN_SECONDS)


def revoke_session(session: Session, reason: str) -> None:
    if session.revoked_at is None:
        session.revoked_at = timezone.now()
        session.revoke_reason = reason
        session.save(update_fields=["revoked_at", "revoke_reason"])
    _deny(session.id)


def revoke_all_sessions(user: User, reason: str) -> int:
    """Ends every session and invalidates every outstanding access token of the user."""
    live = list(Session.objects.filter(user=user, revoked_at__isnull=True))
    for session in live:
        revoke_session(session, reason)
    User.objects.filter(id=user.id).update(session_version=user.session_version + 1)
    user.session_version += 1
    return len(live)


def active_membership(user_id: UUID) -> Membership | None:
    with system_context():
        return (
            Membership.objects.select_related("user", "organization")
            .filter(user_id=user_id, status=MembershipStatus.ACTIVE)
            .first()
        )


def refresh(refresh_token: str, *, device_id: UUID | None) -> TokenPair:
    # Failures raise only after the transaction commits, so a reuse revocation sticks.
    pair: TokenPair | None = None
    with transaction.atomic():
        record = (
            RefreshToken.objects.select_for_update()
            .select_related("session", "session__user")
            .filter(token_hash=hash_token(refresh_token))
            .first()
        )
        now = timezone.now()
        if record is not None:
            session = record.session
            membership = active_membership(session.user_id)
            if record.used_at is not None:
                # A rotated token came back: someone holds a copy. End the whole family.
                revoke_session(session, "refresh_token_reuse")
                audit.record(
                    action="auth.refresh_token_reused",
                    object_type="session",
                    object_id=session.id,
                    organization_id=membership.organization_id if membership else None,
                    diff={"user_id": session.user_id},
                )
            elif (
                session.revoked_at is None
                and session.expires_at > now
                and membership is not None
                and session.user.status == UserStatus.ACTIVE
                and membership.organization.status == OrganizationStatus.ACTIVE
                and (session.client != SessionClient.MOBILE or session.device_id == device_id)
            ):
                record.used_at = now
                record.save(update_fields=["used_at"])
                session.last_used_at = now
                if session.client == SessionClient.MOBILE:
                    session.expires_at = now + _session_lifetime(SessionClient.MOBILE)
                session.save(update_fields=["last_used_at", "expires_at"])
                new_refresh = _new_refresh_token(session)
                access, access_expires = access_token_for(session, membership)
                pair = TokenPair(
                    access, access_expires, new_refresh, session.expires_at, session.id
                )
    if pair is None:
        raise InvalidRefreshToken()
    return pair


def resolve_actor(claims: tokens.AccessClaims) -> Actor:
    """Rebuild the actor from the database on every request; the token only names the session."""
    if cache.get(f"{_DENY_PREFIX}{claims.session_id}"):
        raise TokenRevoked()
    membership = active_membership(claims.user_id)
    if (
        membership is None
        or membership.organization_id != claims.organization_id
        or membership.organization.status != OrganizationStatus.ACTIVE
        or membership.user.status != UserStatus.ACTIVE
        or membership.user.session_version != claims.session_version
    ):
        raise TokenRevoked()
    granted = frozenset(
        Perm(p) for p in membership.granted_permissions if p in Perm._value2member_map_
    )
    return Actor(
        user_id=membership.user_id,
        organization_id=membership.organization_id,
        role=Role(membership.role),
        scope=Scope(ScopeKind(membership.scope_type), frozenset(membership.scope_ids)),
        granted=granted,
        session_id=claims.session_id,
        mfa_at=claims.mfa_at,
    )


def logout(actor: Actor) -> None:
    if actor.session_id is None:
        return
    with transaction.atomic():
        session = Session.objects.filter(id=actor.session_id, user_id=actor.user_id).first()
        if session is not None:
            revoke_session(session, "logout")
        audit.record(
            action="auth.signed_out", object_type="session", object_id=actor.session_id, actor=actor
        )
