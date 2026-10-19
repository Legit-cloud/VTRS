"""Assignment reads: the admin's deployment view and the agent's own assignments (FR-6.2.5)."""

from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from rest_framework.exceptions import NotFound

from apps.core.authz import authorize
from apps.core.domain.actor import Actor
from apps.core.domain.permissions import Perm
from apps.elections.domain.rules import ElectionStatus

from .models import AgentAssignment, AssignmentStatus

# Agents keep seeing an assignment until the election closes.
VISIBLE_TO_AGENTS = (
    ElectionStatus.DRAFT,
    ElectionStatus.CONFIGURED,
    ElectionStatus.LOCKED,
    ElectionStatus.LIVE,
)


def assignments_for(actor: Actor) -> QuerySet[AgentAssignment]:
    authorize(actor, Perm.ASSIGNMENTS_MANAGE)
    return AgentAssignment.objects.for_actor(actor).select_related(
        "election", "polling_unit", "agent"
    )


def assignment_for(actor: Actor, assignment_id: UUID) -> AgentAssignment:
    assignment = assignments_for(actor).filter(id=assignment_id).first()
    if assignment is None:
        raise NotFound()
    return assignment


def active_assignment(actor: Actor, *, election_id: UUID, polling_unit_id: UUID) -> bool:
    """Whether the acting agent is deployed to this polling unit (used by result submission)."""
    authorize(actor, Perm.RESULTS_SUBMIT)
    return (
        AgentAssignment.objects.for_actor(actor)
        .filter(
            agent_id=actor.user_id,
            election_id=election_id,
            polling_unit_id=polling_unit_id,
            status=AssignmentStatus.ACTIVE,
        )
        .exists()
    )


def my_assignments(actor: Actor) -> list[dict[str, Any]]:
    """What the agent sees before capture: which election and which polling unit (FR-6.2.5).
    The parties to enter come from the result form, which is resolved per unit."""
    authorize(actor, Perm.RESULTS_SUBMIT)
    rows = (
        AgentAssignment.objects.for_actor(actor)
        .filter(
            agent_id=actor.user_id,
            status=AssignmentStatus.ACTIVE,
            election__status__in=VISIBLE_TO_AGENTS,
        )
        .select_related("election", "election__election_type", "polling_unit", "ward", "lga")
        .order_by("election__election_date", "polling_unit__inec_code")
    )
    return [
        {
            "assignment_id": assignment.id,
            "election": {
                "id": assignment.election.id,
                "name": assignment.election.name,
                "election_type_name": assignment.election.election_type.name,
                "election_date": assignment.election.election_date,
                "status": assignment.election.status,
                "capture_open": assignment.election.status == ElectionStatus.LIVE,
                "polls_open_at": assignment.election.polls_open_at,
                "polls_close_at": assignment.election.polls_close_at,
            },
            "polling_unit": {
                "id": assignment.polling_unit.id,
                "inec_code": assignment.polling_unit.inec_code,
                "name": assignment.polling_unit.name,
                "ward": assignment.ward.name,
                "lga": assignment.lga.name,
                "latitude": assignment.polling_unit.latitude,
                "longitude": assignment.polling_unit.longitude,
                "registered_voters": assignment.polling_unit.registered_voters,
            },
        }
        for assignment in rows
    ]
