"""Asynchronous anomaly analysis (FR-6.9.2 - FR-6.9.5): the contextual, statistical and evidence
rules that need other rows to answer. Inline rules (arithmetic, over-voting, duplicates) stay in
the submit transaction; these run on a worker after the result is safely stored.

Every entry point is idempotent. A flag is raised at most once per (version, rule), so a
redelivered event or a periodic sweep never doubles the queue. A finding never changes what is
counted; it routes a result to a human.
"""

import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import F, Max
from django.utils import timezone

from apps.core import rls
from apps.core.rls import system_context
from apps.evidence.domain.rules import EvidenceStatus
from apps.evidence.models import EvidenceFile
from apps.results.domain.versions import REPORTED_STATES
from apps.results.models import ResultVersion

from . import services
from .domain.contextual import (
    Figures,
    Thresholds,
    duplicate_evidence,
    exif_findings,
    gps_findings,
    statistical_findings,
    timing_findings,
)
from .domain.inline import Finding, RuleCode
from .models import AnomalyFlag

logger = logging.getLogger("vtrs.anomalies")

REPORTED = [s.value for s in REPORTED_STATES]


def thresholds() -> Thresholds:
    overrides: dict[str, Any] = getattr(settings, "VTRS_ANOMALY_THRESHOLDS", {})
    return Thresholds(**overrides)


def _as_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _new_only(version_id: UUID, findings: list[Finding]) -> list[Finding]:
    """Drop findings whose rule already has a flag on this version (any status)."""
    seen = set(
        AnomalyFlag.objects.filter(result_version_id=version_id).values_list("rule_code", flat=True)
    )
    fresh: dict[str, Finding] = {}
    for finding in findings:
        if finding.rule.value not in seen and finding.rule.value not in fresh:
            fresh[finding.rule.value] = finding
    return list(fresh.values())


def _raise(version: ResultVersion, findings: list[Finding], pu: Any, election_id: UUID) -> int:
    fresh = _new_only(version.id, findings)
    if not fresh:
        return 0
    services.raise_flags(
        fresh,
        organization_id=version.organization_id,
        election_id=election_id,
        contest_id=version.contest_id,
        polling_unit=pu,
        result_version_id=version.id,
    )
    services.sync_version_state(version.id)
    return len(fresh)


# --- A newly stored result ---------------------------------------------------------------------


def _peer_figures(
    version: ResultVersion, ward_id: UUID, lga_id: UUID, t: Thresholds
) -> list[Figures]:
    """Counting results at comparable polling units: the ward's, widened to the LGA's when the
    ward is too small for the statistics to mean anything."""
    base = (
        ResultVersion.objects.filter(
            contest_id=version.contest_id,
            pu_result__head_version_id=F("id"),
            state__in=REPORTED,
        )
        .exclude(id=version.id)
        .annotate(top=Max("vote_lines__votes"), registered=F("polling_unit__registered_voters"))
    )
    for scope in ({"ward_id": ward_id}, {"lga_id": lga_id}):
        rows = list(
            base.filter(**scope).values_list(
                "valid", "rejected", "total_cast", "accredited", "registered", "top"
            )
        )
        if len(rows) >= t.min_peers:
            return [Figures(v, r, c, a, reg, top or 0) for v, r, c, a, reg, top in rows]
    return []


def analyze_version(organization_id: UUID, version_id: UUID) -> int:
    """Run GPS, timing and statistical rules on a stored version. Returns flags raised."""
    t = thresholds()
    with transaction.atomic():
        rls.set_tenant(organization_id)
        version = (
            ResultVersion.objects.select_related("polling_unit", "pu_result", "contest__election")
            .filter(id=version_id)
            .first()
        )
        if version is None:
            return 0
        pu = version.polling_unit
        election = version.contest.election
        findings = gps_findings(
            lat=_as_float(version.gps_lat),
            lng=_as_float(version.gps_lng),
            accuracy_m=_as_float(version.gps_accuracy_m),
            pu_lat=_as_float(pu.latitude),
            pu_lng=_as_float(pu.longitude),
            t=t,
        ) + timing_findings(
            captured_at=version.device_captured_at,
            received_at=version.server_received_at,
            polls_open_at=election.polls_open_at,
            polls_close_at=election.polls_close_at,
            t=t,
        )
        if version.pu_result.head_version_id == version.id:
            top = (
                version.vote_lines.aggregate(top=Max("votes"))["top"]
                if version.vote_lines.exists()
                else 0
            )
            own = Figures(
                version.valid,
                version.rejected,
                version.total_cast,
                version.accredited,
                pu.registered_voters,
                top or 0,
            )
            findings += statistical_findings(
                own, _peer_figures(version, version.ward_id, version.lga_id, t), t
            )
        return _raise(version, findings, pu, election.id)


# --- Evidence ----------------------------------------------------------------------------------


def _naive(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso).replace(tzinfo=None)
    except ValueError:
        return None


def analyze_evidence(organization_id: UUID, evidence_id: UUID) -> int:
    """Duplicate-photo and EXIF checks on a verified photo."""
    t = thresholds()
    with transaction.atomic():
        rls.set_tenant(organization_id)
        evidence = (
            EvidenceFile.objects.select_related(
                "polling_unit", "result_version", "result_version__pu_result"
            )
            .filter(id=evidence_id, status=EvidenceStatus.VERIFIED)
            .first()
        )
        if evidence is None:
            return 0
        version = evidence.result_version
        election_id = version.pu_result.election_id
        pu = evidence.polling_unit
        meta = evidence.metadata or {}
        others = [
            (unit_id, dhash, sha or "")
            for unit_id, dhash, sha in EvidenceFile.objects.filter(
                result_version__pu_result__election_id=election_id,
                status=EvidenceStatus.VERIFIED,
            )
            .exclude(polling_unit_id=evidence.polling_unit_id)
            .values_list("polling_unit_id", "metadata__dhash", "sha256_server")
        ]
        findings = duplicate_evidence(
            dhash=meta.get("dhash"),
            sha256=evidence.sha256_server,
            others=others,
            t=t,
        ) + exif_findings(
            exif_taken_at=_naive(meta.get("exif_taken_at")),
            device_captured_at=version.device_captured_at,
            exif_gps=meta.get("exif_gps"),
            pu_lat=_as_float(pu.latitude),
            pu_lng=_as_float(pu.longitude),
            t=t,
        )
        for finding in findings:
            finding.details["evidence_id"] = str(evidence.id)
        return _raise(version, findings, pu, election_id)


def flag_quarantined(organization_id: UUID, evidence_id: UUID) -> int:
    with transaction.atomic():
        rls.set_tenant(organization_id)
        evidence = (
            EvidenceFile.objects.select_related(
                "polling_unit", "result_version", "result_version__pu_result"
            )
            .filter(id=evidence_id, status=EvidenceStatus.QUARANTINED)
            .first()
        )
        if evidence is None:
            return 0
        finding = Finding(
            RuleCode.EVIDENCE_QUARANTINED,
            {"evidence_id": str(evidence.id), "reason": evidence.quarantine_reason},
        )
        return _raise(
            evidence.result_version,
            [finding],
            evidence.polling_unit,
            evidence.result_version.pu_result.election_id,
        )


def check_missing_evidence(limit: int = 500) -> int:
    """Sweep: a counting result with no photo uploaded or verified after the wait is flagged."""
    t = thresholds()
    cutoff = timezone.now() - timedelta(minutes=t.evidence_wait_minutes)
    with transaction.atomic(), system_context():
        stale = list(
            ResultVersion.objects.filter(
                pu_result__head_version_id=F("id"),
                state__in=REPORTED,
                server_received_at__lte=cutoff,
                contest__election__status__in=["LIVE", "CLOSED"],
            )
            .exclude(evidence__status__in=[EvidenceStatus.UPLOADED, EvidenceStatus.VERIFIED])
            .exclude(flags__rule_code=RuleCode.MISSING_EVIDENCE.value)
            .values_list("organization_id", "id")
            .distinct()[:limit]
        )
    raised = 0
    for organization_id, version_id in stale:
        with transaction.atomic():
            rls.set_tenant(organization_id)
            version = (
                ResultVersion.objects.select_related("polling_unit", "pu_result")
                .filter(id=version_id)
                .first()
            )
            if version is None:
                continue
            raised += _raise(
                version,
                [
                    Finding(
                        RuleCode.MISSING_EVIDENCE,
                        {"waited_minutes": t.evidence_wait_minutes},
                    )
                ],
                version.polling_unit,
                version.pu_result.election_id,
            )
    return raised
