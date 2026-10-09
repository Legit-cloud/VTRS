"""Result submission (spec section 10; FR-6.5.x, FR-6.6.6, AC-05 - AC-08).

Guarantees: a submission is never lost, never counted twice, never silently dropped for being
wrong. Well-formed results are accepted and, when a rule fires, flagged for review; only
malformed or unauthorized ones are refused.

Per item:
 1. payload hash matches the item as sent (integrity of what the device signed off on)
 2. replay check: same version id + same hash -> the stored outcome; different hash -> 409
 3. device, contest, polling unit, election status and assignment checks
 4. ballot and result-sheet shape (every candidate once, exactly the configured totals)
 5. lock the polling unit's result row, assign the next version number, run inline rules
 6. persist version, vote lines, evidence stubs, flags, audit and outbox in one transaction
"""

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from apps.accounts import selectors as accounts
from apps.anomalies import services as anomalies
from apps.anomalies.domain.inline import Finding, RuleCode, Totals, arithmetic, merge, over_voting
from apps.assignments import selectors as assignments
from apps.audit import services as audit
from apps.core import services as core
from apps.core.authz import authorize
from apps.core.domain.actor import Actor
from apps.core.domain.permissions import Perm
from apps.elections import selectors as elections
from apps.elections.domain.rules import SHEET_FIELDS, ElectionStatus, JurisdictionLevel, covers
from apps.evidence import services as evidence
from apps.evidence.errors import EvidenceConflict
from apps.geography import selectors as geography

from .domain.versions import VersionState, select_head, submission_hash
from .models import PuResult, PuResultStatus, ResultVersion, VoteLine

CAPTURE_STATES = {ElectionStatus.LIVE, ElectionStatus.CLOSED}


def failed(version_id: Any, http_status: int, code: str, detail: str, errors: Any = None) -> dict:
    outcome = {
        "version_id": str(version_id) if version_id else None,
        "status": "FAILED",
        "http_status": http_status,
        "code": code,
        "detail": detail,
        "replayed": False,
    }
    if errors:
        outcome["errors"] = errors
    return outcome


def _accepted(version: ResultVersion, *, replayed: bool) -> dict:
    flags = sorted(
        version.flags.filter(status="OPEN").values_list("rule_code", flat=True).distinct()
    )
    stubs = version.evidence.order_by("created_at")
    return {
        "version_id": str(version.id),
        "status": "REQUIRES_REVIEW" if version.state == VersionState.REQUIRES_REVIEW else "SYNCED",
        "http_status": 200,
        "replayed": replayed,
        "version_no": version.version_no,
        "state": version.state,
        "is_head": version.pu_result.head_version_id == version.id,
        "flags": flags,
        "evidence_uploads": [evidence.upload_instructions(e) for e in stubs],
    }


def _replay_or_conflict(
    actor: Actor, existing: ResultVersion | None, item_hash: str, version_id: Any
) -> dict:
    if (
        existing is not None
        and existing.submitted_by_id == actor.user_id
        and existing.payload_hash == item_hash
    ):
        return _accepted(existing, replayed=True)
    with transaction.atomic():
        audit.record(
            action="result.idempotency_conflict",
            object_type="result_version",
            object_id=version_id,
            actor=actor,
            diff={"payload_hash": item_hash},
        )
    return failed(
        version_id,
        409,
        "idempotency_conflict",
        "This version id was already used for a different submission.",
    )


def _sheet_problems(sheet_fields: list[str], totals: Mapping[str, Any]) -> list[str]:
    problems = []
    for name in SHEET_FIELDS:
        provided = totals.get(name) is not None
        required = name in sheet_fields
        if required and not provided:
            problems.append(f"{name} is required for this contest")
        elif provided and not required:
            problems.append(f"{name} is not captured for this contest")
    return problems


def _flag_unassigned(actor: Actor, election: Any, contest: Any, pu: Any) -> None:
    with transaction.atomic():
        anomalies.raise_flags(
            [Finding(RuleCode.UNASSIGNED_PU_ATTEMPT, {"agent_id": str(actor.user_id)})],
            organization_id=actor.organization_id,
            election_id=election.id,
            contest_id=contest.id,
            polling_unit=pu,
            raised_by_id=actor.user_id,
        )
        audit.record(
            action="result.unassigned_attempt",
            object_type="polling_unit",
            object_id=pu.id,
            actor=actor,
            diff={"contest_id": contest.id},
        )


def submit(actor: Actor, item: Mapping[str, Any], raw: Mapping[str, Any]) -> dict:
    """Process one validated submission item; `raw` is the item exactly as the device sent it."""
    authorize(actor, Perm.RESULTS_SUBMIT)
    version_id = item["version_id"]
    item_hash = submission_hash(raw)
    if item["payload_hash"].lower() != item_hash:
        return failed(
            version_id, 400, "payload_hash_mismatch", "payload_hash does not match the item."
        )

    existing = ResultVersion.objects.filter(id=version_id).first()
    if existing is not None:
        return _replay_or_conflict(actor, existing, item_hash, version_id)

    device = accounts.session_device(actor)
    if device is None or device.id != item["device_id"]:
        return failed(
            version_id, 403, "device_mismatch", "Submit from the device you signed in on."
        )
    try:
        contest = elections.contest_for(actor, item["contest_id"])
    except NotFound:
        return failed(version_id, 404, "unknown_contest", "Unknown contest.")
    election = contest.election
    pu = geography.polling_unit(actor, item["polling_unit_id"])
    if pu is None:
        return failed(version_id, 404, "unknown_polling_unit", "Unknown polling unit.")
    if not covers(
        JurisdictionLevel(contest.jurisdiction_level),
        contest.jurisdiction_ids,
        state_id=pu.state_id,
        lga_id=pu.lga_id,
        ward_id=pu.ward_id,
    ):
        return failed(
            version_id,
            400,
            "contest_not_for_polling_unit",
            "This contest is not held at this polling unit.",
        )
    if ElectionStatus(election.status) not in CAPTURE_STATES:
        return failed(
            version_id, 409, "capture_not_open", "Result capture has not opened for this election."
        )
    if not assignments.active_assignment(actor, election_id=election.id, polling_unit_id=pu.id):
        _flag_unassigned(actor, election, contest, pu)
        return failed(
            version_id, 403, "unassigned_polling_unit", "You are not assigned to this polling unit."
        )

    votes = {line["candidate_id"]: line["votes"] for line in item["votes"]}
    candidate_ids = set(elections.candidates_for(actor, contest).values_list("id", flat=True))
    if len(votes) != len(item["votes"]) or set(votes) != candidate_ids:
        return failed(
            version_id,
            400,
            "candidate_mismatch",
            "Give exactly one line for every candidate in the contest.",
        )
    totals = item["totals"]
    if problems := _sheet_problems(contest.sheet_fields, totals):
        return failed(version_id, 400, "sheet_fields_mismatch", "; ".join(problems))

    findings = arithmetic(
        Totals(
            totals.get("accredited"),
            totals["valid"],
            totals.get("rejected"),
            totals.get("total_cast"),
        ),
        votes,
    ) + over_voting(
        Totals(
            totals.get("accredited"),
            totals["valid"],
            totals.get("rejected"),
            totals.get("total_cast"),
        ),
        pu.registered_voters,
    )
    if election.status == ElectionStatus.CLOSED:
        findings.append(Finding(RuleCode.LATE_SUBMISSION, {"closed_at": election.closed_at}))
    if item["config_version"] != election.config_version:
        findings.append(
            Finding(
                RuleCode.CONFIG_VERSION_MISMATCH,
                {"device": item["config_version"], "server": election.config_version},
            )
        )

    try:
        with transaction.atomic():
            version = _persist(
                actor, item, item_hash, election, contest, pu, device, votes, findings
            )
    except IntegrityError:
        # The same version id won a race on another polling unit, or in another tenant.
        return _replay_or_conflict(
            actor, ResultVersion.objects.filter(id=version_id).first(), item_hash, version_id
        )
    except EvidenceConflict:
        return failed(version_id, 409, "evidence_conflict", EvidenceConflict.default_detail)
    except ValidationError as exc:
        return failed(version_id, 400, "malformed", "The evidence manifest is invalid.", exc.detail)
    if version is None:  # a concurrent identical request committed first
        return _replay_or_conflict(
            actor, ResultVersion.objects.filter(id=version_id).first(), item_hash, version_id
        )
    return _accepted(version, replayed=False)


def _lock_pu_result(actor: Actor, election: Any, contest: Any, pu: Any) -> PuResult:
    pu_result, _ = PuResult.objects.get_or_create(
        contest=contest,
        polling_unit=pu,
        defaults={
            "organization_id": actor.organization_id,
            "election": election,
            "ward_id": pu.ward_id,
            "lga_id": pu.lga_id,
            "state_id": pu.state_id,
        },
    )
    # Serializes every version for this polling unit and contest.
    return PuResult.objects.select_for_update().get(id=pu_result.id)


def _persist(
    actor: Actor,
    item: Mapping[str, Any],
    item_hash: str,
    election: Any,
    contest: Any,
    pu: Any,
    device: Any,
    votes: dict[UUID, int],
    findings: list[Finding],
) -> ResultVersion | None:
    pu_result = _lock_pu_result(actor, election, contest, pu)
    if ResultVersion.objects.filter(id=item["version_id"]).exists():
        return None  # a replay that raced us and committed while we waited for the lock

    previous = list(pu_result.versions.values("id", "version_no", "state", "submitted_by_id"))
    parent = item.get("parent_version_id")
    if previous:
        other_sources = {str(p["submitted_by_id"]) for p in previous} - {str(actor.user_id)}
        if other_sources:
            findings.append(
                Finding(RuleCode.DUPLICATE_SOURCE, {"other_submitters": sorted(other_sources)})
            )
        if parent != pu_result.head_version_id:
            findings.append(
                Finding(
                    RuleCode.VERSION_FORK,
                    {"parent_version_id": parent, "head_version_id": pu_result.head_version_id},
                )
            )
    elif parent is not None:
        findings.append(
            Finding(RuleCode.VERSION_FORK, {"parent_version_id": parent, "head_version_id": None})
        )
    findings = merge(findings)

    totals = item["totals"]
    gps = item.get("gps") or {}
    version = ResultVersion.objects.create(
        id=item["version_id"],
        organization_id=actor.organization_id,
        pu_result=pu_result,
        contest=contest,
        polling_unit=pu,
        ward_id=pu.ward_id,
        lga_id=pu.lga_id,
        version_no=pu_result.version_count + 1,
        accredited=totals.get("accredited"),
        valid=totals["valid"],
        rejected=totals.get("rejected"),
        total_cast=totals.get("total_cast"),
        device_captured_at=item["device_captured_at"],
        server_received_at=timezone.now(),
        gps_lat=gps.get("lat"),
        gps_lng=gps.get("lng"),
        gps_accuracy_m=gps.get("accuracy_m"),
        device=device,
        submitted_by_id=actor.user_id,
        app_version=item["app_version"],
        config_version=item["config_version"],
        payload_hash=item_hash,
        parent_version_id=parent,
        state=VersionState.REQUIRES_REVIEW if findings else VersionState.SUBMITTED,
    )
    VoteLine.objects.bulk_create(
        VoteLine(
            organization_id=actor.organization_id,
            result_version=version,
            candidate_id=candidate_id,
            votes=count,
        )
        for candidate_id, count in votes.items()
    )
    evidence.create_stubs(version, actor.user_id, item.get("evidence", []), election.id)
    if findings:
        anomalies.raise_flags(
            findings,
            organization_id=actor.organization_id,
            election_id=election.id,
            contest_id=contest.id,
            polling_unit=pu,
            result_version_id=version.id,
            raised_by_id=actor.user_id,
        )

    old_head = pu_result.head_version_id
    head_id = select_head(
        [(p["version_no"], p["state"], p["id"]) for p in previous]
        + [(version.version_no, version.state, version.id)]
    )
    head_state = version.state if head_id == version.id else _state_of(previous, head_id)
    pu_result.version_count = version.version_no
    pu_result.head_version_id = head_id
    pu_result.status = head_state or PuResultStatus.NO_RESULT
    pu_result.save(update_fields=["version_count", "head_version", "status", "updated_at"])

    audit.record(
        action="result.version_accepted",
        object_type="result_version",
        object_id=version.id,
        actor=actor,
        diff={
            "pu_result_id": pu_result.id,
            "version_no": version.version_no,
            "state": version.state,
            "flags": [f.rule for f in findings],
            "payload_hash": item_hash,
        },
    )
    core.emit(
        "result.version_accepted",
        {
            "version_id": version.id,
            "pu_result_id": pu_result.id,
            "contest_id": contest.id,
            "ward_id": pu.ward_id,
            "lga_id": pu.lga_id,
            "head_changed": head_id != old_head,
        },
    )
    version.pu_result = pu_result
    return version


def _state_of(previous: Sequence[Mapping[str, Any]], version_id: Any) -> str | None:
    return next((p["state"] for p in previous if p["id"] == version_id), None)
