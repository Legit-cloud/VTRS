"""Election reads. Parties and election configuration are organization-wide reference data:
every member of the organization may read them; changing them needs elections.configure or
candidates.manage. Configuration issues are scoped like results (an agent's own unit, a
coordinator's area)."""

from typing import cast
from uuid import UUID

from django.db.models import IntegerField, OuterRef, Prefetch, QuerySet, Subquery
from rest_framework.exceptions import NotFound

from apps.core.authz import AUTHENTICATED, authorize
from apps.core.domain.actor import Actor
from apps.core.domain.permissions import Perm
from apps.evidence.storage import get_storage
from apps.geography import selectors as geography

from .domain.rules import ContestantSpec, ContestSpec, PartySpec
from .models import Candidate, ConfigIssue, Contest, Election, ElectionParty, Party


def elections_for(actor: Actor) -> QuerySet[Election]:
    authorize(actor, AUTHENTICATED)
    return Election.objects.in_organization(actor).select_related("state", "election_type")


def election_for(actor: Actor, election_id: UUID) -> Election:
    election = elections_for(actor).filter(id=election_id).first()
    if election is None:
        raise NotFound()
    return election


# --- Parties ---------------------------------------------------------------------------------


def parties_for(actor: Actor) -> QuerySet[Party]:
    authorize(actor, AUTHENTICATED)
    return Party.objects.in_organization(actor).order_by("abbreviation")


def party_for(actor: Actor, party_id: UUID) -> Party:
    party = parties_for(actor).filter(id=party_id).first()
    if party is None:
        raise NotFound()
    return party


LOGO_EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
LOGO_URL_SECONDS = 3600


def logo_url(party: Party) -> str | None:
    """A short-lived link to the logo, for an <img>. Logos are not evidence: no custody event."""
    if not party.logo_key:
        return None
    extension = LOGO_EXTENSIONS.get(party.logo_mime, "img")
    return get_storage().presign_download(
        party.logo_key,
        filename=f"{party.abbreviation.lower()}.{extension}",
        inline=True,
        expires_in=LOGO_URL_SECONDS,
    )


def election_parties(actor: Actor, election: Election) -> QuerySet[ElectionParty]:
    """The contesting parties in the admin's fixed order."""
    authorize(actor, AUTHENTICATED)
    return (
        ElectionParty.objects.in_organization(actor)
        .filter(election=election)
        .select_related("party")
        .order_by("ballot_order")
    )


def party_specs(actor: Actor, election: Election) -> list[PartySpec]:
    return [
        PartySpec(ep.party_id, ep.party.abbreviation, ep.ballot_order)
        for ep in election_parties(actor, election)
    ]


# --- Contests and contestants ----------------------------------------------------------------


def _ballot_order() -> Subquery:
    return Subquery(
        ElectionParty.objects.filter(
            election_id=OuterRef("contest__election_id"), party_id=OuterRef("party_id")
        ).values("ballot_order")[:1],
        output_field=IntegerField(),
    )


def contests_for(actor: Actor, election: Election) -> QuerySet[Contest]:
    authorize(actor, AUTHENTICATED)
    return (
        Contest.objects.in_organization(actor)
        .filter(election=election)
        .select_related("constituency")
        .order_by("constituency__name")
    )


def contest_for(actor: Actor, contest_id: UUID) -> Contest:
    authorize(actor, AUTHENTICATED)
    contest = (
        Contest.objects.in_organization(actor)
        .select_related("election", "constituency")
        .filter(id=contest_id)
        .first()
    )
    if contest is None:
        raise NotFound()
    return contest


def contest_at(actor: Actor, election: Election, polling_unit_id: UUID) -> Contest | None:
    """The race a polling unit votes in for this election: its constituency of the election
    type's kind, then that constituency's contest. None when either link is missing."""
    kind = election.election_type.constituency_kind
    constituency = geography.constituency_of(actor, polling_unit_id, kind)
    if constituency is None:
        return None
    return (
        contests_for(actor, election)
        .select_related("election", "election__election_type")
        .filter(constituency=constituency)
        .first()
    )


def candidates_for(actor: Actor, contest: Contest) -> QuerySet[Candidate]:
    """A contest's contestants in the election's party order, each with its party."""
    authorize(actor, AUTHENTICATED)
    qs = (
        Candidate.objects.in_organization(actor)
        .filter(contest=contest)
        .select_related("party")
        .annotate(ballot_order=_ballot_order())
        .order_by("ballot_order", "party__abbreviation")
    )
    return cast("QuerySet[Candidate]", qs)


def contestants_for(
    actor: Actor, election: Election, *, constituency_id: UUID | None = None
) -> QuerySet[Candidate]:
    authorize(actor, AUTHENTICATED)
    qs = (
        Candidate.objects.in_organization(actor)
        .filter(contest__election=election)
        .select_related("party", "contest", "contest__constituency")
        .annotate(ballot_order=_ballot_order())
    )
    if constituency_id is not None:
        qs = qs.filter(contest__constituency_id=constituency_id)
    return cast("QuerySet[Candidate]", qs.order_by("contest__constituency__name", "ballot_order"))


def candidate_for(actor: Actor, candidate_id: UUID) -> Candidate:
    authorize(actor, AUTHENTICATED)
    candidate = (
        Candidate.objects.in_organization(actor)
        .select_related("contest", "contest__election", "contest__constituency", "party")
        .annotate(ballot_order=_ballot_order())
        .filter(id=candidate_id)
        .first()
    )
    if candidate is None:
        raise NotFound()
    return candidate


def contest_specs(actor: Actor, election: Election) -> list[ContestSpec]:
    contests = contests_for(actor, election).prefetch_related(
        Prefetch("candidates", queryset=Candidate.objects.order_by("party_id"))
    )
    return [
        ContestSpec(
            id=c.id,
            constituency_id=c.constituency_id,
            constituency_name=c.constituency.name,
            contestants=tuple(ContestantSpec(k.id, k.name, k.party_id) for k in c.candidates.all()),
        )
        for c in contests
    ]


# --- Configuration issues (FR-6.3.7) ---------------------------------------------------------


def issues_for(actor: Actor, election: Election) -> QuerySet[ConfigIssue]:
    authorize(actor, Perm.ELECTIONS_CONFIGURE)
    return (
        ConfigIssue.objects.for_actor(actor)
        .filter(election=election)
        .select_related("polling_unit", "ward", "lga", "raised_by", "resolved_by")
    )


def issue_for(actor: Actor, issue_id: UUID) -> ConfigIssue:
    authorize(actor, Perm.ELECTIONS_CONFIGURE)
    issue = ConfigIssue.objects.for_actor(actor).filter(id=issue_id).first()
    if issue is None:
        raise NotFound()
    return issue


def open_issue_count(actor: Actor, election: Election) -> int:
    return issues_for(actor, election).filter(status="OPEN").count()
