"""Scoped reads. Out-of-scope objects are indistinguishable from missing ones (404)."""

from uuid import UUID

from django.db.models import QuerySet
from rest_framework.exceptions import NotFound

from apps.core.authz import AUTHENTICATED, authorize
from apps.core.domain.actor import Actor
from apps.core.domain.permissions import Perm

from .models import Device, DeviceStatus, Invitation, Membership, MembershipStatus


def members_for(actor: Actor) -> QuerySet[Membership]:
    authorize(actor, Perm.USERS_MANAGE)
    return (
        Membership.objects.for_actor(actor)
        .filter(status=MembershipStatus.ACTIVE)
        .select_related("user")
    )


def member_for(actor: Actor, user_id: UUID) -> Membership:
    membership = members_for(actor).filter(user_id=user_id).first()
    if membership is None:
        raise NotFound()
    return membership


def session_device(actor: Actor) -> Device | None:
    """The active device this session was opened on (agents sign in from one device)."""
    authorize(actor, AUTHENTICATED)
    if actor.session_id is None:
        return None
    return Device.objects.filter(
        session__id=actor.session_id,
        session__user_id=actor.user_id,
        status=DeviceStatus.ACTIVE,
    ).first()


def agent_for(actor: Actor, user_id: UUID) -> Membership:
    """An active agent in the actor's organization, for deployment (assignments.manage)."""
    authorize(actor, Perm.ASSIGNMENTS_MANAGE)
    membership = (
        Membership.objects.in_organization(actor)
        .select_related("user")
        .filter(user_id=user_id, status=MembershipStatus.ACTIVE)
        .first()
    )
    if membership is None:
        raise NotFound()
    return membership


def devices_of(actor: Actor, membership: Membership) -> QuerySet[Device]:
    """Devices of a member the actor can already see (pass the result of `member_for`)."""
    authorize(actor, Perm.USERS_MANAGE)
    if membership.organization_id != actor.organization_id:
        raise NotFound()
    return Device.objects.filter(user_id=membership.user_id).order_by("-created_at")


def invitations_for(actor: Actor) -> QuerySet[Invitation]:
    authorize(actor, Perm.USERS_MANAGE)
    return Invitation.objects.for_actor(actor)


def invitation_for(actor: Actor, invitation_id: UUID) -> Invitation:
    invitation = invitations_for(actor).filter(id=invitation_id).first()
    if invitation is None:
        raise NotFound()
    return invitation


def own_membership(actor: Actor) -> Membership:
    authorize(actor, AUTHENTICATED)
    # Not geographic scoping: everyone may read their own membership.
    return Membership.objects.select_related("user", "organization").get(
        organization_id=actor.organization_id,
        user_id=actor.user_id,
        status=MembershipStatus.ACTIVE,
    )
