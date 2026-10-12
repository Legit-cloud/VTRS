"""Raising flags and working them: acknowledge, assign, comment, resolve, reopen (FR-6.9.7).

Everything here runs in the caller's transaction. Every change is a `FlagEvent` (who, when,
why) plus an audit entry, and announces itself on the outbox so rollups (open-flag counts) and
alert routing stay current.
"""

from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import Membership, MembershipStatus
from apps.audit import services as audit
from apps.core import services as core
from apps.core.authz import authorize, require_recent_mfa
from apps.core.domain.actor import Actor
from apps.core.domain.canonical import to_json_compatible
from apps.core.domain.permissions import Perm, Role, effective_permissions
from apps.results.domain.versions import VersionState
from apps.results.models import PuResult, PuResultStatus, ResultVersion

from .domain.escalation import config_problems
from .domain.inline import Finding, Severity
from .errors import FlagAlreadyClosed, FlagNotClosed, InvalidAssignee
from .models import AlertPolicy, AnomalyFlag, FlagAction, FlagEvent, FlagStatus

ACTIVE = (FlagStatus.OPEN, FlagStatus.ACKNOWLEDGED)
# Findings at or above this severity send a result to review; INFO is for the record.
REVIEW_SEVERITIES = {Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL}


def _event(
    flag: AnomalyFlag,
    action: str,
    *,
    actor_id: UUID | None = None,
    from_status: str = "",
    to_status: str = "",
    note: str = "",
    details: dict[str, Any] | None = None,
) -> FlagEvent:
    return FlagEvent.objects.create(
        organization_id=flag.organization_id,
        flag=flag,
        action=action,
        from_status=from_status,
        to_status=to_status,
        actor_id=actor_id,
        note=note,
        details=to_json_compatible(details or {}),
        at=timezone.now(),
    )


def _announce_change(flag: AnomalyFlag, topic: str = "anomaly.flag_changed") -> None:
    core.emit(
        topic,
        {
            "organization_id": flag.organization_id,
            "election_id": flag.election_id,
            "contest_id": flag.contest_id,
            "ward_id": flag.ward_id,
            "lga_id": flag.lga_id,
            "flag_id": flag.id,
            "version_id": flag.result_version_id,
        },
    )


# --- Raising --------------------------------------------------------------------------------


def raise_flags(
    findings: list[Finding],
    *,
    organization_id: Any,
    election_id: Any,
    contest_id: Any,
    polling_unit: Any,
    result_version_id: Any = None,
    raised_by_id: Any = None,
) -> list[AnomalyFlag]:
    flags = [
        AnomalyFlag(
            organization_id=organization_id,
            election_id=election_id,
            contest_id=contest_id,
            polling_unit=polling_unit,
            ward_id=polling_unit.ward_id,
            lga_id=polling_unit.lga_id,
            result_version_id=result_version_id,
            raised_by_id=raised_by_id,
            rule_code=finding.rule,
            severity=finding.severity,
            details=to_json_compatible(finding.details),
        )
        for finding in findings
    ]
    AnomalyFlag.objects.bulk_create(flags)
    now = timezone.now()
    FlagEvent.objects.bulk_create(
        FlagEvent(
            organization_id=organization_id,
            flag=flag,
            action=FlagAction.RAISED,
            to_status=FlagStatus.OPEN,
            actor_id=raised_by_id,
            details={"rule": flag.rule_code, "severity": flag.severity},
            at=now,
        )
        for flag in flags
    )
    for flag in flags:
        audit.record(
            action="anomaly.flag_raised",
            object_type="anomaly_flag",
            object_id=flag.id,
            organization_id=organization_id,
            diff={
                "rule": flag.rule_code,
                "severity": flag.severity,
                "polling_unit_id": polling_unit.id,
                "result_version_id": result_version_id,
            },
        )
    if flags:
        core.emit(
            "anomaly.flags_raised",
            {
                "organization_id": organization_id,
                "election_id": election_id,
                "contest_id": contest_id,
                "ward_id": polling_unit.ward_id,
                "lga_id": polling_unit.lga_id,
                "flag_ids": [f.id for f in flags],
            },
        )
    return flags


# --- Keeping the result's review state honest ---------------------------------------------------


def sync_version_state(version_id: UUID | None) -> str | None:
    """A result carries REQUIRES_REVIEW while any flag worth a human's time is still active.

    Approved and rejected results are decisions, not flag states, so they are left alone.
    Returns the new state if it changed."""
    if version_id is None:
        return None
    version = ResultVersion.objects.filter(id=version_id).first()
    if version is None or version.state not in {
        VersionState.SUBMITTED,
        VersionState.REQUIRES_REVIEW,
    }:
        return None
    needs_review = AnomalyFlag.objects.filter(
        result_version_id=version_id,
        status__in=ACTIVE,
        severity__in=[s.value for s in REVIEW_SEVERITIES],
    ).exists()
    wanted = VersionState.REQUIRES_REVIEW if needs_review else VersionState.SUBMITTED
    if wanted == version.state:
        return None
    ResultVersion.objects.filter(id=version_id).update(state=wanted)
    PuResult.objects.filter(id=version.pu_result_id, head_version_id=version_id).update(
        status=PuResultStatus(wanted.value)
    )
    return wanted.value


# --- Working a flag -------------------------------------------------------------------------------


def _locked(flag: AnomalyFlag) -> AnomalyFlag:
    return AnomalyFlag.objects.select_for_update().get(id=flag.id)


def _changed(
    flag: AnomalyFlag,
    actor: Actor,
    action: str,
    audit_action: str,
    *,
    from_status: str,
    note: str = "",
    details: dict[str, Any] | None = None,
) -> AnomalyFlag:
    _event(
        flag,
        action,
        actor_id=actor.user_id,
        from_status=from_status,
        to_status=flag.status,
        note=note,
        details=details,
    )
    audit.record(
        action=audit_action,
        object_type="anomaly_flag",
        object_id=flag.id,
        actor=actor,
        diff={"from": from_status, "to": flag.status, "note": note, **(details or {})},
    )
    sync_version_state(flag.result_version_id)
    _announce_change(flag)
    return flag


def acknowledge(actor: Actor, flag: AnomalyFlag) -> AnomalyFlag:
    """Mark a flag as seen and being handled. Stops the escalation clock."""
    authorize(actor, Perm.ANOMALIES_VIEW)
    with transaction.atomic():
        flag = _locked(flag)
        if flag.status != FlagStatus.OPEN:
            return flag  # already acknowledged or closed: acknowledging again is harmless
        before = flag.status
        flag.status = FlagStatus.ACKNOWLEDGED
        flag.acknowledged_at = timezone.now()
        flag.acknowledged_by_id = actor.user_id
        flag.sla_due_at = None
        flag.save(
            update_fields=[
                "status",
                "acknowledged_at",
                "acknowledged_by_id",
                "sla_due_at",
                "updated_at",
            ]
        )
        return _changed(
            flag, actor, FlagAction.ACKNOWLEDGED, "anomaly.flag_acknowledged", from_status=before
        )


def comment(actor: Actor, flag: AnomalyFlag, note: str) -> AnomalyFlag:
    authorize(actor, Perm.ANOMALIES_VIEW)
    with transaction.atomic():
        _event(flag, FlagAction.COMMENTED, actor_id=actor.user_id, note=note)
        audit.record(
            action="anomaly.flag_commented",
            object_type="anomaly_flag",
            object_id=flag.id,
            actor=actor,
            diff={"note": note},
        )
    return flag


def assign(actor: Actor, flag: AnomalyFlag, assignee_id: UUID | None) -> AnomalyFlag:
    """Give a flag to a named person in scope of it (or clear the assignment)."""
    authorize(actor, Perm.ANOMALIES_RESOLVE)
    if assignee_id is not None:
        member = (
            Membership.objects.filter(
                user_id=assignee_id,
                organization_id=flag.organization_id,
                status=MembershipStatus.ACTIVE,
            )
            .select_related("user")
            .first()
        )
        if member is None or not _covers(member, flag) or not _may_view(member):
            raise InvalidAssignee()
    with transaction.atomic():
        flag = _locked(flag)
        if flag.status in {FlagStatus.RESOLVED, FlagStatus.FALSE_POSITIVE}:
            raise FlagAlreadyClosed()
        flag.assigned_to_id = assignee_id
        flag.save(update_fields=["assigned_to", "updated_at"])
        _event(
            flag,
            FlagAction.ASSIGNED,
            actor_id=actor.user_id,
            details={"assigned_to": assignee_id},
        )
        audit.record(
            action="anomaly.flag_assigned",
            object_type="anomaly_flag",
            object_id=flag.id,
            actor=actor,
            diff={"assigned_to": assignee_id},
        )
    return flag


def resolve(actor: Actor, flag: AnomalyFlag, *, outcome: str, note: str) -> AnomalyFlag:
    """Close a flag as RESOLVED (it was real and has been dealt with) or FALSE_POSITIVE."""
    authorize(actor, Perm.ANOMALIES_RESOLVE)
    if outcome not in {FlagStatus.RESOLVED, FlagStatus.FALSE_POSITIVE}:
        raise ValidationError({"outcome": ["Use RESOLVED or FALSE_POSITIVE."]})
    if len(note.strip()) < 3:
        raise ValidationError({"note": ["Say what was found or done."]})
    with transaction.atomic():
        flag = _locked(flag)
        if flag.status in {FlagStatus.RESOLVED, FlagStatus.FALSE_POSITIVE}:
            raise FlagAlreadyClosed()
        before = flag.status
        flag.status = FlagStatus(outcome)
        flag.resolved_at = timezone.now()
        flag.resolved_by_id = actor.user_id
        flag.resolution_note = note.strip()
        flag.sla_due_at = None
        flag.save(
            update_fields=[
                "status",
                "resolved_at",
                "resolved_by_id",
                "resolution_note",
                "sla_due_at",
                "updated_at",
            ]
        )
        action = (
            FlagAction.RESOLVED if outcome == FlagStatus.RESOLVED else FlagAction.FALSE_POSITIVE
        )
        return _changed(
            flag,
            actor,
            action,
            f"anomaly.flag_{outcome.lower()}",
            from_status=before,
            note=note.strip(),
        )


def reopen(actor: Actor, flag: AnomalyFlag, note: str) -> AnomalyFlag:
    authorize(actor, Perm.ANOMALIES_RESOLVE)
    if len(note.strip()) < 3:
        raise ValidationError({"note": ["Say why this is being reopened."]})
    with transaction.atomic():
        flag = _locked(flag)
        if flag.status not in {FlagStatus.RESOLVED, FlagStatus.FALSE_POSITIVE}:
            raise FlagNotClosed()
        before = flag.status
        flag.status = FlagStatus.OPEN
        flag.resolved_at = None
        flag.resolved_by_id = None
        flag.acknowledged_at = None
        flag.acknowledged_by_id = None
        flag.save(
            update_fields=[
                "status",
                "resolved_at",
                "resolved_by_id",
                "acknowledged_at",
                "acknowledged_by_id",
                "updated_at",
            ]
        )
        return _changed(
            flag,
            actor,
            FlagAction.REOPENED,
            "anomaly.flag_reopened",
            from_status=before,
            note=note.strip(),
        )


# --- Who may see a flag ---------------------------------------------------------------------


def _covers(member: Membership, flag: AnomalyFlag) -> bool:
    if member.scope_type == "ORG":
        return True
    if member.scope_type == "LGA":
        return flag.lga_id in set(member.scope_ids)
    if member.scope_type == "WARD":
        return flag.ward_id in set(member.scope_ids)
    return False


def _may_view(member: Membership) -> bool:
    granted = {Perm(p) for p in member.granted_permissions if p in Perm._value2member_map_}
    return Perm.ANOMALIES_VIEW in effective_permissions(Role(member.role), granted)


# --- Alert policy (spec section 13: configuration of communication channels) ----------------


def set_alert_policy(actor: Actor, matrix: dict[str, Any]) -> AlertPolicy:
    """Replace the organization's override of the escalation matrix.

    Admins only, with a fresh second factor: this decides who is woken up, and a quiet matrix
    is as dangerous as a noisy one. Only the severities named here change."""
    authorize(actor, Perm.ALERTS_CONFIGURE)
    require_recent_mfa(actor)
    problems = config_problems(matrix)
    if problems:
        raise ValidationError({"matrix": problems})
    with transaction.atomic():
        existing = (
            AlertPolicy.objects.select_for_update()
            .filter(organization_id=actor.organization_id)
            .first()
        )
        before = existing.matrix if existing else {}
        policy = existing or AlertPolicy(organization_id=actor.organization_id)
        policy.matrix = to_json_compatible(matrix)
        policy.updated_by_id = actor.user_id
        policy.updated_at = timezone.now()
        policy.save()
        audit.record(
            action="alert_policy.updated",
            object_type="alert_policy",
            object_id=policy.id,
            actor=actor,
            diff={"before": before, "after": policy.matrix},
        )
    return policy


def clear_alert_policy(actor: Actor) -> bool:
    """Go back to the platform defaults."""
    authorize(actor, Perm.ALERTS_CONFIGURE)
    require_recent_mfa(actor)
    with transaction.atomic():
        existing = (
            AlertPolicy.objects.select_for_update()
            .filter(organization_id=actor.organization_id)
            .first()
        )
        if existing is None:
            return False
        audit.record(
            action="alert_policy.cleared",
            object_type="alert_policy",
            object_id=existing.id,
            actor=actor,
            diff={"before": existing.matrix},
        )
        existing.delete()
    return True
