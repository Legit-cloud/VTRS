"""Result reads: the agent's form, own submissions and assignments, and the oversight views
(review queue and polling-unit version history) scoped to the actor's geography."""

from typing import Any
from uuid import UUID

from django.db.models import F, Prefetch, QuerySet
from rest_framework.exceptions import NotFound

from apps.assignments import selectors as assignments
from apps.core.authz import authorize
from apps.core.domain.actor import Actor
from apps.core.domain.permissions import Perm
from apps.elections import selectors as elections
from apps.geography import selectors as geography

from .domain.sheet import TOTALS
from .domain.versions import Completion, VersionState, completion_of
from .models import PuResult, ResultReview, ResultVersion, VoteLine


def own_versions(actor: Actor) -> QuerySet[ResultVersion]:
    authorize(actor, Perm.RESULTS_SUBMIT)
    return ResultVersion.objects.for_actor(actor).filter(submitted_by_id=actor.user_id)


def own_version(actor: Actor, version_id: UUID) -> ResultVersion | None:
    return own_versions(actor).select_related("pu_result").filter(id=version_id).first()


def completion(version: ResultVersion) -> Completion:
    """NUMBERS_SUBMITTED until a result sheet is uploaded for this version, then COMPLETE."""
    return completion_of(e.status for e in version.evidence.all())


def _latest_review(version: ResultVersion) -> dict[str, Any] | None:
    decision = max(version.reviews.all(), key=lambda r: r.decided_at, default=None)
    if decision is None:
        return None
    return {
        "decision": decision.decision,
        "reason": decision.reason,
        "decided_at": decision.decided_at,
    }


def status_view(version: ResultVersion) -> dict[str, Any]:
    """What the agent sees about one submission: review state, completion and why."""
    return {
        "version_id": version.id,
        "election_id": version.pu_result.election_id,
        "polling_unit_id": version.polling_unit_id,
        "version_no": version.version_no,
        "state": version.state,
        "is_head": version.pu_result.head_version_id == version.id,
        "completion": completion(version),
        "server_received_at": version.server_received_at,
        # Why a result was rejected, so the agent knows what to correct.
        "review": _latest_review(version),
        "flags": sorted(
            {f.rule_code for f in version.flags.all() if f.status == "OPEN"},
        ),
        "evidence": [
            {"evidence_id": e.id, "kind": e.kind, "mime": e.mime, "status": e.status}
            for e in sorted(version.evidence.all(), key=lambda e: e.created_at)
        ],
    }


def submission_status(actor: Actor, version_id: UUID) -> dict[str, Any]:
    version = (
        own_versions(actor)
        .select_related("pu_result")
        .prefetch_related("evidence", "reviews", "flags")
        .filter(id=version_id)
        .first()
    )
    if version is None:
        raise NotFound()
    return status_view(version)


def _head_for(actor: Actor, election_id: UUID, polling_unit_id: UUID) -> ResultVersion | None:
    result = (
        PuResult.objects.for_actor(actor)
        .filter(election_id=election_id, polling_unit_id=polling_unit_id)
        .select_related("head_version")
        .first()
    )
    if result is None or result.head_version is None:
        return None
    return (
        ResultVersion.objects.filter(id=result.head_version_id)
        .select_related("pu_result")
        .prefetch_related("evidence", "reviews", "flags", "vote_lines")
        .first()
    )


def my_assignments(actor: Actor) -> list[dict[str, Any]]:
    """The agent's assignments, each with the result that currently counts for the unit and
    the agent's latest submission there (so a rejected one still shows its reason)."""
    rows = assignments.my_assignments(actor)
    for row in rows:
        election_id, pu_id = row["election"]["id"], row["polling_unit"]["id"]
        head = _head_for(actor, election_id, pu_id)
        latest = (
            own_versions(actor)
            .filter(pu_result__election_id=election_id, polling_unit_id=pu_id)
            .select_related("pu_result")
            .prefetch_related("evidence", "reviews", "flags")
            .order_by("-version_no")
            .first()
        )
        row["result"] = status_view(head) if head else None
        row["my_latest"] = status_view(latest) if latest else None
    return rows


def result_form(actor: Actor, election_id: UUID, polling_unit_id: UUID) -> dict[str, Any]:
    """The result form for one assigned unit (FR-6.5.1): exactly the parties configured for the
    election and the unit's constituency, in the admin's order, each with its candidate.

    Agents can read it only for units they are assigned to; nothing on it is editable except
    the numbers."""
    authorize(actor, Perm.RESULTS_SUBMIT)
    election = elections.election_for(actor, election_id)
    if not assignments.active_assignment(
        actor, election_id=election.id, polling_unit_id=polling_unit_id
    ):
        raise NotFound()
    pu = geography.polling_unit(actor, polling_unit_id)
    if pu is None:
        raise NotFound()
    contest = elections.contest_at(actor, election, pu.id)
    rows = []
    if contest is not None:
        for candidate in elections.candidates_for(actor, contest):
            rows.append(
                {
                    "candidate_id": candidate.id,
                    "candidate_name": candidate.name,
                    "party_id": candidate.party_id,
                    "party_abbreviation": candidate.party.abbreviation,
                    "party_name": candidate.party.full_name,
                    "party_logo_url": elections.logo_url(candidate.party),
                    "ballot_order": candidate.ballot_order,
                }
            )
    head = _head_for(actor, election.id, pu.id)
    current = None
    if head is not None:
        current = {
            **status_view(head),
            "totals": {name: getattr(head, name) for name in TOTALS},
            "votes": {str(line.candidate_id): line.votes for line in head.vote_lines.all()},
        }
    return {
        "election_id": election.id,
        "election_name": election.name,
        "election_status": election.status,
        "capture_open": election.status == "LIVE",
        "config_version": election.config_version,
        "polling_unit": {
            "id": pu.id,
            "inec_code": pu.inec_code,
            "name": pu.name,
            "ward": pu.ward.name,
            "lga": pu.lga.name,
        },
        "constituency": (
            {"id": contest.constituency_id, "name": contest.constituency.name}
            if contest is not None
            else None
        ),
        "parties": rows,
        "totals": list(TOTALS),
        "current": current,
    }


REVIEWABLE = (VersionState.SUBMITTED, VersionState.REQUIRES_REVIEW)


def review_queue(actor: Actor, election_id: UUID) -> QuerySet[ResultVersion]:
    """Head versions waiting for verification, oldest first, inside the actor's scope."""
    authorize(actor, Perm.RESULTS_REVIEW)
    return (
        ResultVersion.objects.for_actor(actor)
        .filter(
            pu_result__election_id=election_id,
            pu_result__head_version_id=F("id"),
            state__in=REVIEWABLE,
        )
        .select_related("polling_unit", "ward", "lga", "contest__constituency", "submitted_by")
        .prefetch_related(
            Prefetch("vote_lines", queryset=VoteLine.objects.select_related("candidate__party")),
            "flags",
            "evidence",
        )
        .order_by("server_received_at", "id")
    )


def pu_history(actor: Actor, election_id: UUID, polling_unit_id: UUID) -> PuResult | None:
    """A polling unit's full version ledger for one election, with reviews, flags and evidence."""
    authorize(actor, Perm.DASHBOARD_VIEW)
    return (
        PuResult.objects.for_actor(actor)
        .filter(election_id=election_id, polling_unit_id=polling_unit_id)
        .select_related("polling_unit", "ward", "lga", "contest__constituency")
        .prefetch_related(
            Prefetch(
                "versions",
                queryset=ResultVersion.objects.select_related("submitted_by")
                .prefetch_related(
                    Prefetch(
                        "vote_lines", queryset=VoteLine.objects.select_related("candidate__party")
                    ),
                    "flags",
                    "evidence",
                    Prefetch(
                        "reviews",
                        queryset=ResultReview.objects.select_related("decided_by").order_by(
                            "decided_at"
                        ),
                    ),
                )
                .order_by("version_no"),
            )
        )
        .first()
    )
