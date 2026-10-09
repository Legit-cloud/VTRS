"""Result reads for the submitting agent. Oversight views (scoped lists, drill-down, version
history) arrive with the dashboards in M4."""

from typing import Any
from uuid import UUID

from django.db.models import QuerySet

from apps.core.authz import authorize
from apps.core.domain.actor import Actor
from apps.core.domain.permissions import Perm

from .models import ResultVersion


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
        .prefetch_related("evidence")
    }
    rows: list[dict[str, Any]] = []
    for version_id in version_ids:
        version = versions.get(version_id)
        if version is None:
            rows.append({"version_id": str(version_id), "status": "UNKNOWN"})
            continue
        rows.append(
            {
                "version_id": str(version.id),
                "status": "REQUIRES_REVIEW" if version.state == "REQUIRES_REVIEW" else "SYNCED",
                "state": version.state,
                "version_no": version.version_no,
                "is_head": version.pu_result.head_version_id == version.id,
                "server_received_at": version.server_received_at,
                "evidence": [
                    {"evidence_id": str(e.id), "status": e.status}
                    for e in sorted(version.evidence.all(), key=lambda e: e.created_at)
                ],
            }
        )
    return rows
