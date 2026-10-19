"""Result submission (spec section 10; FR-6.5.x, FR-6.6.6, AC-05 - AC-08, AC-16).

Guarantees: a submission is never counted twice and never silently dropped for being
suspicious. Valid results are accepted and, when a rule fires, flagged for review; invalid or
unauthorized ones are refused with a precise code.

Per submission:
 1. payload hash matches the item as sent (what the agent's browser signed off on)
 2. replay check: same version id + same hash -> the stored outcome; different hash -> 409
 3. election status, polling unit and assignment checks; resolve the unit's contest
 4. the form: every configured party exactly once; the sheet's arithmetic limits
 5. lock the polling unit's result row, assign the next version number, run inline rules
 6. persist version, vote lines, flags, audit and outbox in one transaction
The result sheet follows as evidence; the submission is complete once it is uploaded.
"""

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from apps.anomalies import services as anomalies
from apps.anomalies.domain.inline import Finding, RuleCode, Totals, arithmetic, merge, over_voting
from apps.assignments import selectors as assignments
from apps.audit import services as audit
from apps.core import services as core
from apps.core.authz import authorize
from apps.core.domain.actor import Actor
from apps.core.domain.permissions import Perm
from apps.elections import selectors as elections
from apps.elections import services as election_services
from apps.elections.domain.rules import ElectionStatus
from apps.geography import selectors as geography

from .domain.sheet import arithmetic_problem, party_problem
from .domain.versions import (
    Completion,
    ReviewDecision,
    VersionState,
    completion_of,
    decided_state,
    is_fork,
    select_head,
    submission_hash,
)
from .errors import (
    AlreadyDecided,
    EvidenceRequired,
    FlagsUnacknowledged,
    NotHeadVersion,
    ResultsFrozen,
)
from .models import PuResult, PuResultStatus, ResultReview, ResultVersion, VoteLine

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
    return {
        "version_id": str(version.id),
        "status": "REQUIRES_REVIEW"
        if version.state == VersionState.REQUIRES_REVIEW
        else "ACCEPTED",
        "http_status": 200,
        "replayed": replayed,
        "version_no": version.version_no,
        "state": version.state,
        "is_head": version.pu_result.head_version_id == version.id,
        "completion": completion_of(version.evidence.values_list("status", flat=True)),
        "flags": flags,
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
        "This submission id was already used for a different submission.",
    )


def _flag_unassigned(actor: Actor, election: Any, contest_id: Any, pu: Any) -> None:
    with transaction.atomic():
        anomalies.raise_flags(
            [Finding(RuleCode.UNASSIGNED_PU_ATTEMPT, {"agent_id": str(actor.user_id)})],
            organization_id=actor.organization_id,
            election_id=election.id,
            contest_id=contest_id,
            polling_unit=pu,
            raised_by_id=actor.user_id,
        )
        audit.record(
            action="result.unassigned_attempt",
            object_type="polling_unit",
            object_id=pu.id,
            actor=actor,
            diff={"election_id": election.id},
        )


def submit(actor: Actor, item: Mapping[str, Any], raw: Mapping[str, Any]) -> dict:
    """Process one validated submission; `raw` is the body exactly as the browser sent it."""
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

    try:
        election = elections.election_for(actor, item["election_id"])
    except NotFound:
        return failed(version_id, 404, "unknown_election", "Unknown election.")
    pu = geography.polling_unit(actor, item["polling_unit_id"])
    if pu is None:
        return failed(version_id, 404, "unknown_polling_unit", "Unknown polling unit.")
    if ElectionStatus(election.status) not in CAPTURE_STATES:
        return failed(
            version_id, 409, "capture_not_open", "Result capture has not opened for this election."
        )
    contest = elections.contest_at(actor, election, pu.id)
    if not assignments.active_assignment(actor, election_id=election.id, polling_unit_id=pu.id):
        _flag_unassigned(actor, election, contest.id if contest else None, pu)
        return failed(
            version_id, 403, "unassigned_polling_unit", "You are not assigned to this polling unit."
        )
    if contest is None:
        return failed(
            version_id,
            409,
            "no_contest_for_polling_unit",
            "No parties are set up for this polling unit's constituency. Tell an admin.",
        )

    configured = {c.id: c.party.abbreviation for c in elections.candidates_for(actor, contest)}
    lines = [line["candidate_id"] for line in item["votes"]]
    if problem := party_problem(lines, configured, configured):
        return failed(version_id, 400, problem.code, problem.detail, problem.errors)
    votes = {line["candidate_id"]: line["votes"] for line in item["votes"]}
    totals = item["totals"]
    if problem := arithmetic_problem(sum(votes.values()), totals):
        return failed(version_id, 400, problem.code, problem.detail, problem.errors)

    sheet = Totals(
        totals["accredited"], sum(votes.values()), totals["rejected"], totals["total_cast"]
    )
    findings = arithmetic(sheet, votes) + over_voting(sheet, pu.registered_voters)
    if election.status == ElectionStatus.CLOSED:
        findings.append(Finding(RuleCode.LATE_SUBMISSION, {"closed_at": election.closed_at}))
    if item["config_version"] != election.config_version:
        findings.append(
            Finding(
                RuleCode.CONFIG_VERSION_MISMATCH,
                {"client": item["config_version"], "server": election.config_version},
            )
        )

    try:
        with transaction.atomic():
            version = _persist(actor, item, item_hash, election, contest, pu, votes, findings)
    except IntegrityError:
        # The same version id won a race on another polling unit, or in another tenant.
        return _replay_or_conflict(
            actor, ResultVersion.objects.filter(id=version_id).first(), item_hash, version_id
        )
    if version is None:  # a concurrent identical request committed first
        return _replay_or_conflict(
            actor, ResultVersion.objects.filter(id=version_id).first(), item_hash, version_id
        )
    return _accepted(version, replayed=False)


def _lock_pu_result(actor: Actor, election: Any, contest: Any, pu: Any) -> PuResult:
    pu_result, _ = PuResult.objects.get_or_create(
        election=election,
        polling_unit=pu,
        defaults={
            "organization_id": actor.organization_id,
            "contest": contest,
            "ward_id": pu.ward_id,
            "lga_id": pu.lga_id,
            "state_id": pu.state_id,
        },
    )
    # Serializes every version for this polling unit and election.
    return PuResult.objects.select_for_update().get(id=pu_result.id)


def _persist(
    actor: Actor,
    item: Mapping[str, Any],
    item_hash: str,
    election: Any,
    contest: Any,
    pu: Any,
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
    latest = max(previous, key=lambda p: p["version_no"])["id"] if previous else None
    if is_fork(parent, head_id=pu_result.head_version_id, latest_id=latest):
        findings.append(
            Finding(
                RuleCode.VERSION_FORK,
                {"parent_version_id": parent, "head_version_id": pu_result.head_version_id},
            )
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
        accredited=totals["accredited"],
        valid=sum(votes.values()),
        rejected=totals["rejected"],
        total_cast=totals["total_cast"],
        device_captured_at=item["device_captured_at"],
        server_received_at=timezone.now(),
        gps_lat=gps.get("lat"),
        gps_lng=gps.get("lng"),
        gps_accuracy_m=gps.get("accuracy_m"),
        submitted_by_id=actor.user_id,
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
            "organization_id": actor.organization_id,
            "election_id": election.id,
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


# --- "Party or contestant missing" (FR-6.3.7) -------------------------------------------------


def report_config_issue(
    actor: Actor, election_id: UUID, *, polling_unit_id: UUID, kind: str, note: str
) -> Any:
    """An agent tells the admins the form does not match the sheet. It creates a task, never a
    party or contestant, and only for a unit the agent is assigned to."""
    authorize(actor, Perm.RESULTS_SUBMIT)
    election = elections.election_for(actor, election_id)
    if not assignments.active_assignment(
        actor, election_id=election.id, polling_unit_id=polling_unit_id
    ):
        raise NotFound()
    pu = geography.polling_unit(actor, polling_unit_id)
    if pu is None:
        raise NotFound()
    return election_services.record_issue(actor, election, pu, kind=kind, note=note)


# --- Review: verify against the sheet (FR-6.7.4, FR-6.7.5) -----------------------------------

REVIEWABLE_ELECTION_STATES = {ElectionStatus.LIVE, ElectionStatus.CLOSED}


def review(
    actor: Actor,
    version_id: UUID,
    *,
    decision: str,
    reason: str = "",
    acknowledge_flags: bool = False,
) -> dict[str, Any]:
    """Verify (approve) or reject the head version of a polling unit's result.

    A result is verified against its uploaded sheet, so it cannot be approved before the sheet
    is attached. Rejection keeps the original record; the agent sends a corrected version, and
    the head falls back to the latest version that has not been rejected. The decision, its
    reason and the reviewer are recorded in an append-only ledger and the audit log.
    """
    authorize(actor, Perm.RESULTS_REVIEW)
    wanted = ReviewDecision(decision)
    if wanted is ReviewDecision.REJECTED and len(reason.strip()) < 3:
        raise ValidationError({"reason": ["A reason is required when rejecting a result."]})
    visible = ResultVersion.objects.for_actor(actor).filter(id=version_id).first()
    if visible is None:
        raise NotFound()

    with transaction.atomic():
        pu_result = PuResult.objects.select_for_update().get(id=visible.pu_result_id)
        version = ResultVersion.objects.get(id=version_id)
        election = elections.election_for(actor, pu_result.election_id)
        if ElectionStatus(election.status) not in REVIEWABLE_ELECTION_STATES:
            raise ResultsFrozen()
        if pu_result.head_version_id != version.id:
            raise NotHeadVersion()
        new_state = decided_state(version.state, wanted)
        if new_state is None:
            raise AlreadyDecided()
        if wanted is ReviewDecision.APPROVED and (
            completion_of(version.evidence.values_list("status", flat=True))
            is not Completion.COMPLETE
        ):
            raise EvidenceRequired()
        open_flags = sorted(
            version.flags.filter(status="OPEN").values_list("rule_code", flat=True).distinct()
        )
        if wanted is ReviewDecision.APPROVED and open_flags and not acknowledge_flags:
            raise FlagsUnacknowledged({"flags": open_flags})

        previous_state = version.state
        ResultVersion.objects.filter(id=version.id).update(state=new_state)
        siblings = list(pu_result.versions.values_list("version_no", "state", "id"))
        head_id = select_head(siblings)
        head_state = next((s for _, s, i in siblings if i == head_id), None)
        pu_result.head_version_id = head_id
        pu_result.status = head_state or PuResultStatus.NO_RESULT
        pu_result.save(update_fields=["head_version", "status", "updated_at"])

        record = ResultReview.objects.create(
            organization_id=actor.organization_id,
            result_version=version,
            pu_result=pu_result,
            contest_id=version.contest_id,
            polling_unit_id=version.polling_unit_id,
            ward_id=version.ward_id,
            lga_id=version.lga_id,
            decision=wanted,
            from_state=previous_state,
            reason=reason.strip(),
            acknowledged_flags=open_flags if wanted is ReviewDecision.APPROVED else [],
            decided_by_id=actor.user_id,
            decided_at=timezone.now(),
        )
        audit.record(
            action="result.review_decided",
            object_type="result_version",
            object_id=version.id,
            actor=actor,
            diff={
                "decision": wanted,
                "from": previous_state,
                "to": new_state,
                "reason": record.reason,
                "acknowledged_flags": record.acknowledged_flags,
                "new_head_version_id": head_id,
            },
        )
        core.emit(
            "result.review_decided",
            {
                "version_id": version.id,
                "pu_result_id": pu_result.id,
                "organization_id": actor.organization_id,
                "election_id": pu_result.election_id,
                "contest_id": version.contest_id,
                "ward_id": version.ward_id,
                "lga_id": version.lga_id,
                "decision": wanted,
            },
        )
    return {
        "version_id": str(version.id),
        "decision": wanted.value,
        "state": new_state.value,
        "head_version_id": str(head_id) if head_id else None,
        "pu_status": pu_result.status,
        "decided_at": record.decided_at,
    }
