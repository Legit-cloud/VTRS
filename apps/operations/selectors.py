"""Operational views for organization admins (spec section 13): system health, programme
analytics (section 12) and master-data quality.

Infrastructure checks are about the shared platform and expose only counts and ages. Everything
about people and results is read through the tenant, so it is the organization's own.
"""

import statistics
import time
from datetime import timedelta
from typing import Any
from uuid import UUID

from celery import current_app
from django.core.cache import cache
from django.db import connection
from django.db.models import Count, Min
from django.utils import timezone

from apps.accounts.models import Invitation
from apps.aggregation.models import Rollup
from apps.anomalies.models import AnomalyFlag, FlagStatus
from apps.assignments.models import AgentAssignment
from apps.audit.models import AuditEvent
from apps.core.authz import authorize
from apps.core.domain.actor import Actor, ScopeKind
from apps.core.domain.permissions import Perm
from apps.core.models import OutboxEvent
from apps.elections import selectors as elections
from apps.evidence.domain.rules import EvidenceStatus
from apps.evidence.models import EvidenceFile
from apps.evidence.storage import get_storage
from apps.geography.models import Lga, PollingUnit
from apps.notifications.models import Delivery
from apps.reports.models import ExportJob
from apps.results.models import ResultVersion

OK, DEGRADED, DOWN = "ok", "degraded", "down"
_RANK = {OK: 0, DEGRADED: 1, DOWN: 2}
OFFLINE_AFTER = timedelta(minutes=5)


def _timed(fn: Any) -> tuple[str, float, str]:
    started = time.perf_counter()
    try:
        fn()
    except Exception as exc:
        return DOWN, round((time.perf_counter() - started) * 1000, 1), type(exc).__name__
    return OK, round((time.perf_counter() - started) * 1000, 1), ""


def _age(oldest: Any) -> float | None:
    return None if oldest is None else round((timezone.now() - oldest).total_seconds(), 1)


def _by_age(age: float | None, degraded: float, down: float) -> str:
    if age is None or age < degraded:
        return OK
    return DOWN if age >= down else DEGRADED


def system_health(actor: Actor) -> dict[str, Any]:
    authorize(actor, Perm.SYSTEM_VIEW)

    def db() -> None:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")

    def cache_ping() -> None:
        cache.set("health:ping", "1", 5)
        if cache.get("health:ping") != "1":
            raise RuntimeError("cache did not return what was written")

    def broker() -> None:
        with current_app.connection_for_write() as conn:
            conn.ensure_connection(max_retries=1, timeout=2)

    def storage() -> None:
        get_storage().size_of("health/none")

    components: dict[str, dict[str, Any]] = {}
    for name, fn in (
        ("database", db),
        ("cache", cache_ping),
        ("broker", broker),
        ("storage", storage),
    ):
        status, ms, detail = _timed(fn)
        components[name] = {"status": status, "latency_ms": ms, "detail": detail}

    oldest_outbox = OutboxEvent.objects.filter(published_at__isnull=True).aggregate(
        n=Count("id"), oldest=Min("created_at")
    )
    age = _age(oldest_outbox["oldest"])
    components["outbox"] = {
        "status": _by_age(age, 60, 300),
        "unpublished": oldest_outbox["n"],
        "oldest_seconds": age,
    }
    unsealed = AuditEvent.objects.filter(batch_id__isnull=True).aggregate(
        n=Count("id"), oldest=Min("at")
    )
    age = _age(unsealed["oldest"])
    components["audit_sealing"] = {
        "status": _by_age(age, 60, 600),
        "unsealed": unsealed["n"],
        "oldest_seconds": age,
    }

    # What follows is this organization's own work in flight.
    cutoff = timezone.now() - timedelta(minutes=10)
    stuck_uploads = EvidenceFile.objects.filter(
        organization_id=actor.organization_id,
        status=EvidenceStatus.PENDING_UPLOAD,
        created_at__lte=cutoff,
    ).count()
    components["evidence"] = {
        "status": DEGRADED if stuck_uploads else OK,
        "uploads_waiting_over_10_min": stuck_uploads,
        "quarantined": EvidenceFile.objects.filter(
            organization_id=actor.organization_id, status=EvidenceStatus.QUARANTINED
        ).count(),
    }
    deliveries = Delivery.objects.filter(organization_id=actor.organization_id)
    failed = deliveries.filter(status="FAILED").count()
    components["notifications"] = {
        "status": DEGRADED if failed else OK,
        "pending": deliveries.filter(status="PENDING").count(),
        "failed": failed,
    }
    jobs = ExportJob.objects.filter(organization_id=actor.organization_id)
    day_ago = timezone.now() - timedelta(days=1)
    failed_exports = jobs.filter(status="FAILED", finished_at__gte=day_ago).count()
    components["exports"] = {
        "status": DEGRADED if failed_exports else OK,
        "in_progress": jobs.filter(status__in=["PENDING", "RUNNING"]).count(),
        "failed_last_24h": failed_exports,
    }
    critical = AnomalyFlag.objects.filter(
        organization_id=actor.organization_id, status=FlagStatus.OPEN, severity="CRITICAL"
    ).count()
    components["flags"] = {
        "status": DEGRADED if critical else OK,
        "open_critical": critical,
        "open_total": AnomalyFlag.objects.filter(
            organization_id=actor.organization_id, status=FlagStatus.OPEN
        ).count(),
    }
    overall = max((c["status"] for c in components.values()), key=_RANK.__getitem__)
    return {"status": overall, "checked_at": timezone.now(), "components": components}


# --- Programme analytics (spec section 12) -------------------------------------------------------


def _rate(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def analytics(actor: Actor, election_id: UUID) -> dict[str, Any]:
    """Onboarding, capture and sync performance, and integrity, inside the caller's scope."""
    authorize(actor, Perm.DASHBOARD_VIEW)
    election = elections.election_for(actor, election_id)
    versions = ResultVersion.objects.for_actor(actor).filter(contest__election_id=election.id)
    first = versions.filter(version_no=1)

    metrics: dict[str, Any] = {"election_id": election.id}

    # Onboarding and activation: organization-wide, so only for organization-scoped callers.
    if actor.scope.kind is ScopeKind.ORG:
        invited = Invitation.objects.in_organization(actor).filter(role="PU_AGENT")
        sent = invited.count()
        accepted = invited.filter(accepted_at__isnull=False).count()
        metrics["invitations"] = {
            "sent": sent,
            "accepted": accepted,
            "activation_rate_pct": _rate(accepted, sent),
        }
    expected = sum(
        Rollup.objects.for_actor(actor)
        .filter(
            election_id=election.id,
            level={"ORG": "STATE", "LGA": "LGA", "WARD": "WARD"}[actor.scope.kind.value],
        )
        .values_list("expected_pus", flat=True)
    )
    assigned = (
        AgentAssignment.objects.for_actor(actor)
        .filter(election_id=election.id, status="ACTIVE")
        .values("polling_unit_id")
        .distinct()
        .count()
    )
    reported = first.values("polling_unit_id").distinct().count()
    metrics["assignment"] = {
        "expected_polling_units": expected,
        "assigned_polling_units": assigned,
        "completion_pct": _rate(assigned, expected),
    }
    metrics["capture"] = {
        "polling_units_reported": reported,
        "submission_completion_pct": _rate(reported, expected),
        "versions": versions.count(),
        "corrections": versions.filter(version_no__gt=1).count(),
    }

    delays = [
        (r - c).total_seconds()
        for c, r in first.values_list("device_captured_at", "server_received_at")
    ]
    offline = [d for d in delays if d > OFFLINE_AFTER.total_seconds()]
    metrics["sync"] = {
        "submissions": len(delays),
        "offline_pct": _rate(len(offline), len(delays)),
        "average_sync_delay_seconds": round(statistics.fmean(offline), 1) if offline else None,
        "median_sync_delay_seconds": round(statistics.median(offline), 1) if offline else None,
        "p90_sync_delay_seconds": (
            round(statistics.quantiles(offline, n=10)[-1], 1) if len(offline) >= 10 else None
        ),
    }

    files = EvidenceFile.objects.for_actor(actor).filter(
        result_version__contest__election_id=election.id
    )
    verified = files.filter(status=EvidenceStatus.VERIFIED).count()
    quarantined = files.filter(status=EvidenceStatus.QUARANTINED).count()
    stale_cutoff = timezone.now() - timedelta(minutes=10)
    stuck = files.filter(status=EvidenceStatus.PENDING_UPLOAD, created_at__lte=stale_cutoff).count()
    metrics["evidence"] = {
        "verified": verified,
        "quarantined": quarantined,
        "stuck_uploads": stuck,
        "upload_success_pct": _rate(verified, verified + quarantined + stuck),
    }

    flags = AnomalyFlag.objects.for_actor(actor).filter(election_id=election.id)
    closed = flags.filter(status__in=[FlagStatus.RESOLVED, FlagStatus.FALSE_POSITIVE])
    took = [
        (resolved - created).total_seconds()
        for resolved, created in closed.filter(resolved_at__isnull=False).values_list(
            "resolved_at", "created_at"
        )
    ]
    flagged_versions = (
        flags.exclude(result_version__isnull=True).values("result_version_id").distinct().count()
    )
    metrics["integrity"] = {
        "flags_raised": flags.count(),
        "flagged_result_pct": _rate(flagged_versions, versions.count()),
        "duplicate_evidence_flags": flags.filter(rule_code="DUPLICATE_EVIDENCE").count(),
        "false_positive_pct": _rate(
            flags.filter(status=FlagStatus.FALSE_POSITIVE).count(), closed.count()
        ),
        "average_minutes_to_resolve": (round(statistics.fmean(took) / 60, 1) if took else None),
        "escalated": flags.filter(escalation_level__gt=0).count(),
    }
    return metrics


# --- Master-data quality -------------------------------------------------------------------------


def data_quality(actor: Actor) -> dict[str, Any]:
    """Gaps in the shared polling-unit directory that weaken the GPS and turnout rules."""
    authorize(actor, Perm.SYSTEM_VIEW)
    total = PollingUnit.objects.count()
    no_coordinates = PollingUnit.objects.filter(latitude__isnull=True)
    no_registered = PollingUnit.objects.filter(registered_voters__isnull=True)
    per_lga = {
        row["lga_id"]: row["n"]
        for row in no_coordinates.values("lga_id").annotate(n=Count("id")).order_by("-n")[:10]
    }
    names = dict(Lga.objects.filter(id__in=per_lga).values_list("id", "name"))
    return {
        "polling_units": total,
        "without_coordinates": no_coordinates.count(),
        "without_registered_voters": no_registered.count(),
        "coordinates_complete_pct": _rate(total - no_coordinates.count(), total),
        "worst_lgas_for_coordinates": [
            {"lga_id": lga_id, "lga_name": names.get(lga_id, ""), "missing": n}
            for lga_id, n in per_lga.items()
        ],
    }
