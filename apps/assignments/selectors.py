"""Assignment reads: the admin's deployment view and the agent's own assignments (FR-6.2.5)."""

from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from rest_framework.exceptions import NotFound

from apps.core.authz import authorize
from apps.core.domain.actor import Actor
from apps.core.domain.permissions import Perm
from apps.elections import selectors as elections
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
    """What the agent app shows before capture: where, for which election, and the ballot."""
    authorize(actor, Perm.RESULTS_SUBMIT)
    rows = (
        AgentAssignment.objects.for_actor(actor)
        .filter(
            agent_id=actor.user_id,
            status=AssignmentStatus.ACTIVE,
            election__status__in=VISIBLE_TO_AGENTS,
        )
        .select_related("election", "polling_unit", "ward", "lga")
        .order_by("election__election_date", "polling_unit__inec_code")
    )
    result = []
    for assignment in rows:
        election, pu = assignment.election, assignment.polling_unit
        contests = elections.contests_covering(
            actor, election, state_id=pu.state_id, lga_id=pu.lga_id, ward_id=pu.ward_id
        )
        result.append(
            {
                "assignment_id": assignment.id,
                "election": {
                    "id": election.id,
                    "name": election.name,
                    "election_date": election.election_date,
                    "status": election.status,
                    "capture_open": election.status == ElectionStatus.LIVE,
                    "config_version": election.config_version,
                    "polls_open_at": election.polls_open_at,
                    "polls_close_at": election.polls_close_at,
                },
                "polling_unit": {
                    "id": pu.id,
                    "inec_code": pu.inec_code,
                    "name": pu.name,
                    "ward": assignment.ward.name,
                    "lga": assignment.lga.name,
                    "latitude": pu.latitude,
                    "longitude": pu.longitude,
                    "registered_voters": pu.registered_voters,
                },
                "contests": [
                    {
                        "id": contest.id,
                        "office": contest.office,
                        "title": contest.title,
                        "sheet_fields": contest.sheet_fields,
                        "candidates": [
                            {
                                "id": k.id,
                                "name": k.name,
                                "party_acronym": k.party_acronym,
                                "ballot_order": k.ballot_order,
                            }
                            for k in contest.candidates.all()
                        ],
                    }
                    for contest in contests
                ],
            }
        )
    return result
