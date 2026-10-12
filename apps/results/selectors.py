"""Result reads: the submitting agent's own status, and the oversight views (review queue and
polling-unit version history) scoped to the actor's geography."""

from typing import Any
from uuid import UUID

from django.db.models import F, Prefetch, QuerySet

from apps.core.authz import authorize
from apps.core.domain.actor import Actor
from apps.core.domain.permissions import Perm

from .domain.versions import VersionState
from .models import PuResult, ResultReview, ResultVersion, VoteLine


def own_versions(actor: Actor) -> QuerySet[ResultVersion]:
    authorize(actor, Perm.RESULTS_SUBMIT)
    return ResultVersion.objects.for_actor(actor).filter(submitted_by_id=actor.user_id)


def own_version(actor: Actor, version_id: UUID) -> ResultVersion | None:
    return own_versions(actor).select_related("pu_result").filter(id=version_id).first()


def sync_status(actor: Actor, version_ids: list[UUID]) -> list[dict[str, Any]]:
    """GET /sync/status: what the server holds for each id the device asks about."""
    versions = {
        v.id: v
        for v in own_versions(actor)
        .filter(id__in=version_ids)
        .select_related("pu_result")
        .prefetch_related("evidence", "reviews")
    }
    rows: list[dict[str, Any]] = []
    for version_id in version_ids:
        version = versions.get(version_id)
        if version is None:
            rows.append({"version_id": str(version_id), "status": "UNKNOWN"})
            continue
        decision = max(version.reviews.all(), key=lambda r: r.decided_at, default=None)
        rows.append(
            {
                "version_id": str(version.id),
                "status": "REQUIRES_REVIEW" if version.state == "REQUIRES_REVIEW" else "SYNCED",
                "state": version.state,
                "version_no": version.version_no,
                "is_head": version.pu_result.head_version_id == version.id,
                "server_received_at": version.server_received_at,
                # Why a result was rejected, so the agent knows what to correct and resubmit.
                "review": (
                    {
                        "decision": decision.decision,
                        "reason": decision.reason,
                        "decided_at": decision.decided_at,
                    }
                    if decision
                    else None
                ),
                "evidence": [
                    {"evidence_id": str(e.id), "status": e.status}
                    for e in sorted(version.evidence.all(), key=lambda e: e.created_at)
                ],
            }
        )
    return rows


REVIEWABLE = (VersionState.SUBMITTED, VersionState.REQUIRES_REVIEW)


def review_queue(actor: Actor, election_id: UUID) -> QuerySet[ResultVersion]:
    """Head versions waiting for a decision, oldest first, inside the actor's scope."""
    authorize(actor, Perm.RESULTS_REVIEW)
    return (
        ResultVersion.objects.for_actor(actor)
        .filter(
            pu_result__election_id=election_id,
            pu_result__head_version_id=F("id"),
            state__in=REVIEWABLE,
        )
        .select_related("polling_unit", "ward", "lga", "contest", "submitted_by")
        .prefetch_related(
            Prefetch("vote_lines", queryset=VoteLine.objects.select_related("candidate")),
            "flags",
        )
        .order_by("server_received_at", "id")
    )


def pu_history(actor: Actor, contest_id: UUID, polling_unit_id: UUID) -> PuResult | None:
    """A polling unit's full version ledger for one contest, with reviews, flags and evidence."""
    authorize(actor, Perm.DASHBOARD_VIEW)
    return (
        PuResult.objects.for_actor(actor)
        .filter(contest_id=contest_id, polling_unit_id=polling_unit_id)
        .select_related("polling_unit", "ward", "lga", "contest")
        .prefetch_related(
            Prefetch(
                "versions",
                queryset=ResultVersion.objects.select_related("submitted_by")
                .prefetch_related(
                    Prefetch("vote_lines", queryset=VoteLine.objects.select_related("candidate")),
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
