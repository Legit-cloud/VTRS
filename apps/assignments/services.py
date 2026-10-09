"""Agent deployment (FR-6.2.4, AC-03).

An assignment must name an active agent of the organization, a polling unit inside the
election's state and inside the agent's authorized polling units (their membership scope).
How many agents may cover one polling unit is a deployment rule (PB-06), set by
VTRS_MAX_AGENTS_PER_POLLING_UNIT.
"""

from typing import Any

from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts import selectors as accounts
from apps.audit import services as audit
from apps.core.authz import authorize
from apps.core.domain.actor import Actor
from apps.core.domain.permissions import Perm, Role
from apps.elections import selectors as elections
from apps.elections.domain.rules import ASSIGNABLE, ElectionStatus
from apps.geography import selectors as geography

from .errors import AlreadyAssigned, ElectionNotAssignable, PollingUnitFullyAssigned
from .models import AgentAssignment, AssignmentStatus


def assign(
    actor: Actor, *, election_id: Any, agent_id: Any, polling_unit_id: Any
) -> AgentAssignment:
    authorize(actor, Perm.ASSIGNMENTS_MANAGE)
    election = elections.election_for(actor, election_id)
    if ElectionStatus(election.status) not in ASSIGNABLE:
        raise ElectionNotAssignable()
    membership = accounts.agent_for(actor, agent_id)
    if membership.role != Role.PU_AGENT or not membership.user.is_active:
        raise ValidationError({"agent_id": ["Only active polling-unit agents can be assigned."]})
    pu = geography.polling_unit(actor, polling_unit_id)
    if pu is None:
        raise ValidationError({"polling_unit_id": ["Unknown polling unit."]})
    if pu.state_id != election.state_id:
        raise ValidationError(
            {"polling_unit_id": ["This polling unit is outside the election's state."]}
        )
    if pu.id not in set(membership.scope_ids):
        raise ValidationError(
            {"polling_unit_id": ["This polling unit is not among the agent's authorized units."]}
        )

    try:
        with transaction.atomic():
            # Serialize deployments to one polling unit so the per-unit cap holds under
            # concurrency (row locks can't help when no assignment row exists yet).
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    [f"assignment:{election.id}:{pu.id}"],
                )
            active = AgentAssignment.objects.filter(
                election=election, polling_unit=pu, status=AssignmentStatus.ACTIVE
            )
            if active.filter(agent_id=agent_id).exists():
                raise AlreadyAssigned()
            if active.count() >= settings.VTRS_MAX_AGENTS_PER_POLLING_UNIT:
                raise PollingUnitFullyAssigned()
            assignment = AgentAssignment.objects.create(
                organization_id=actor.organization_id,
                election=election,
                agent_id=agent_id,
                polling_unit=pu,
                ward_id=pu.ward_id,
                lga_id=pu.lga_id,
                assigned_by_id=actor.user_id,
            )
            audit.record(
                action="assignment.created",
                object_type="assignment",
                object_id=assignment.id,
                actor=actor,
                diff={"election_id": election.id, "agent_id": agent_id, "polling_unit_id": pu.id},
            )
    except IntegrityError:
        # A concurrent request created the same assignment first.
        raise AlreadyAssigned() from None
    return assignment


def revoke(actor: Actor, assignment: AgentAssignment) -> AgentAssignment:
    authorize(actor, Perm.ASSIGNMENTS_MANAGE)
    with transaction.atomic():
        assignment = AgentAssignment.objects.select_for_update().get(id=assignment.id)
        if assignment.status == AssignmentStatus.ACTIVE:
            assignment.status = AssignmentStatus.REVOKED
            assignment.revoked_at = timezone.now()
            assignment.revoked_by_id = actor.user_id
            assignment.save(update_fields=["status", "revoked_at", "revoked_by_id"])
            audit.record(
                action="assignment.revoked",
                object_type="assignment",
                object_id=assignment.id,
                actor=actor,
                diff={
                    "agent_id": assignment.agent_id,
                    "polling_unit_id": assignment.polling_unit_id,
                },
            )
    return assignment
