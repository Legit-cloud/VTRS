"""Election reads. Election configuration is organization-wide reference data: every member
of the organization may read it; changing it needs elections.configure / candidates.manage."""

from uuid import UUID

from django.db.models import Prefetch, QuerySet
from rest_framework.exceptions import NotFound

from apps.core.authz import AUTHENTICATED, authorize
from apps.core.domain.actor import Actor

from .domain.rules import CandidateSpec, ContestSpec, JurisdictionLevel, covers
from .models import Candidate, Contest, Election


def elections_for(actor: Actor) -> QuerySet[Election]:
    authorize(actor, AUTHENTICATED)
    return Election.objects.in_organization(actor).select_related("state")


def election_for(actor: Actor, election_id: UUID) -> Election:
    election = elections_for(actor).filter(id=election_id).first()
    if election is None:
        raise NotFound()
    return election


def contests_for(actor: Actor, election: Election) -> QuerySet[Contest]:
    authorize(actor, AUTHENTICATED)
    return Contest.objects.in_organization(actor).filter(election=election).order_by("title")


def contest_for(actor: Actor, contest_id: UUID) -> Contest:
    authorize(actor, AUTHENTICATED)
    contest = (
        Contest.objects.in_organization(actor)
        .select_related("election")
        .filter(id=contest_id)
        .first()
    )
    if contest is None:
        raise NotFound()
    return contest


def candidates_for(actor: Actor, contest: Contest) -> QuerySet[Candidate]:
    authorize(actor, AUTHENTICATED)
    return Candidate.objects.in_organization(actor).filter(contest=contest).order_by("ballot_order")


def candidate_for(actor: Actor, candidate_id: UUID) -> Candidate:
    authorize(actor, AUTHENTICATED)
    candidate = (
        Candidate.objects.in_organization(actor)
        .select_related("contest", "contest__election")
        .filter(id=candidate_id)
        .first()
    )
    if candidate is None:
        raise NotFound()
    return candidate


def _with_candidates(actor: Actor, election: Election) -> list[Contest]:
    return list(
        contests_for(actor, election).prefetch_related(
            Prefetch("candidates", queryset=Candidate.objects.order_by("ballot_order"))
        )
    )


def contest_specs(actor: Actor, election: Election) -> list[ContestSpec]:
    return [
        ContestSpec(
            id=c.id,
            office=c.office,
            title=c.title,
            jurisdiction_level=c.jurisdiction_level,
            jurisdiction_ids=tuple(c.jurisdiction_ids),
            sheet_fields=tuple(c.sheet_fields),
            candidates=tuple(
                CandidateSpec(k.id, k.name, k.party_acronym, k.ballot_order, k.is_own_party)
                for k in c.candidates.all()
            ),
        )
        for c in _with_candidates(actor, election)
    ]


def contests_covering(
    actor: Actor, election: Election, *, state_id: UUID, lga_id: UUID, ward_id: UUID
) -> list[Contest]:
    """Contests (with candidates prefetched) whose jurisdiction includes a polling unit."""
    return [
        c
        for c in _with_candidates(actor, election)
        if covers(
            JurisdictionLevel(c.jurisdiction_level),
            c.jurisdiction_ids,
            state_id=state_id,
            lga_id=lga_id,
            ward_id=ward_id,
        )
    ]
