"""Scoped reads. Out-of-scope objects are indistinguishable from missing ones (404)."""

from uuid import UUID

from django.db.models import QuerySet
from rest_framework.exceptions import NotFound

from apps.core.authz import AUTHENTICATED, authorize
from apps.core.domain.actor import Actor
from apps.core.domain.permissions import Perm

from .models import Device, Invitation, Membership, MembershipStatus


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
