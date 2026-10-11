"""Alert routing and escalation (FR-6.9.7, FR-6.12.2, PB-10).

When flags are raised, the people whose geography covers them are told according to the
severity's policy in the matrix. A flag nobody acknowledges within its window climbs one rung
(ward -> LGA -> admin) and the new rung is told, on louder channels. Both steps are idempotent:
`notified_at` and the escalation level are checked under a row lock.
"""

import logging
from collections.abc import Iterable, Mapping
from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Membership, MembershipStatus, UserStatus
from apps.audit import services as audit
from apps.core import rls
from apps.core.rls import system_context
from apps.notifications import services as notifications
from apps.notifications.models import NotificationKind

from .domain.escalation import (
    Channel,
    Level,
    Policy,
    initial_due,
    matrix_from_settings,
    next_level,
    top_level,
)
from .domain.inline import Severity
from .models import AnomalyFlag, FlagAction, FlagEvent, FlagStatus

logger = logging.getLogger("vtrs.anomalies")

RULE_TITLES = {
    "ARITHMETIC_VARIANCE": "Totals do not add up",
    "OVER_VOTING": "More votes than accredited or registered voters",
    "DUPLICATE_SOURCE": "Another source reported the same polling unit",
    "VERSION_FORK": "Correction does not follow the previous version",
    "UNASSIGNED_PU_ATTEMPT": "Submission from an agent not assigned to this unit",
    "LATE_SUBMISSION": "Submitted after polls closed",
    "CONFIG_VERSION_MISMATCH": "Captured against an outdated configuration",
    "GPS_MISSING": "No GPS position with the submission",
    "GPS_OUT_OF_GEOFENCE": "Submitted away from the polling unit",
    "GPS_LOW_ACCURACY": "Imprecise GPS position",
    "DEVICE_CLOCK_AHEAD": "Device clock is ahead of the server",
    "CAPTURED_BEFORE_POLLS_OPEN": "Captured before polls opened",
    "CAPTURED_BEFORE_POLLS_CLOSE": "Captured before polls closed",
    "TURNOUT_OUTLIER": "Turnout is unusual for neighbouring units",
    "VOTE_SHARE_OUTLIER": "Vote share is unusual for neighbouring units",
    "HIGH_REJECTED_RATE": "Unusually many rejected ballots",
    "UNANIMOUS_RESULT": "Every valid vote went to one candidate",
    "DUPLICATE_EVIDENCE": "Result-sheet photo matches another polling unit's",
    "EXIF_TIME_MISMATCH": "Photo time does not match the declared capture time",
    "EXIF_GPS_MISMATCH": "Photo location is far from the polling unit",
    "MISSING_EVIDENCE": "No result-sheet photo after the waiting period",
    "EVIDENCE_QUARANTINED": "Result-sheet photo failed verification",
}


def matrix() -> Mapping[Severity, Policy]:
    return matrix_from_settings(getattr(settings, "VTRS_ESCALATION_MATRIX", None))


def recipients(flag: AnomalyFlag, level: Level) -> list[UUID]:
    """Active users holding the rung of the chain of command that covers this flag."""
    members = Membership.objects.filter(
        organization_id=flag.organization_id,
        status=MembershipStatus.ACTIVE,
        user__status=UserStatus.ACTIVE,
    )
    if level is Level.WARD:
        members = members.filter(role="WARD_OFFICER", scope_ids__contains=[flag.ward_id])
    elif level is Level.LGA:
        members = members.filter(role="LGA_OFFICER", scope_ids__contains=[flag.lga_id])
    else:
        members = members.filter(role="PARTY_ADMIN")
    return list(members.values_list("user_id", flat=True))


def _message(flag: AnomalyFlag, *, escalated: bool) -> tuple[str, str]:
    title = RULE_TITLES.get(flag.rule_code, flag.rule_code)
    prefix = "ESCALATED " if escalated else ""
    return (
        f"{prefix}[{flag.severity}] {title}",
        f"{flag.polling_unit.name} ({flag.polling_unit.inec_code}). Open the flag to review it.",
    )


def _tell(
    flag: AnomalyFlag, levels: Iterable[Level], channels: Iterable[Channel], *, escalated: bool
) -> int:
    """One notification per person, even if they hold several of the rungs being told."""
    wanted: dict[UUID, set[str]] = {}
    for level in levels:
        for user_id in recipients(flag, level):
            wanted.setdefault(user_id, set()).update(c.value for c in channels)
    if not wanted:
        return 0
    title, body = _message(flag, escalated=escalated)
    data = {
        "flag_id": str(flag.id),
        "election_id": str(flag.election_id),
        "polling_unit_id": str(flag.polling_unit_id),
        "rule_code": flag.rule_code,
    }
    # People who want the same channels share one call, so the outbox sees few events.
    by_channels: dict[frozenset[str], list[UUID]] = {}
    for user_id, user_channels in wanted.items():
        by_channels.setdefault(frozenset(user_channels), []).append(user_id)
    for channel_set, users in by_channels.items():
        notifications.notify(
            organization_id=flag.organization_id,
            user_ids=users,
            kind=(NotificationKind.ANOMALY_ESCALATED if escalated else NotificationKind.ANOMALY),
            title=title,
            body=body,
            severity=flag.severity,
            data=data,
            channels=sorted(channel_set),
        )
    return len(wanted)


def route_flags(organization_id: UUID, flag_ids: Iterable[UUID]) -> int:
    """Tell the right people about newly raised flags and start the acknowledgement clock."""
    policies = matrix()
    told = 0
    with transaction.atomic():
        rls.set_tenant(organization_id)
        flags = (
            AnomalyFlag.objects.select_for_update(of=("self",))
            .select_related("polling_unit")
            .filter(id__in=list(flag_ids), notified_at__isnull=True)
        )
        now = timezone.now()
        for flag in flags:
            policy = policies[Severity(flag.severity)]
            flag.notified_at = now
            if policy.notify:
                flag.escalation_level = top_level(policy)
                flag.sla_due_at = initial_due(policy, now)
                told += _tell(flag, policy.notify, policy.channels, escalated=False)
            flag.save(update_fields=["notified_at", "escalation_level", "sla_due_at", "updated_at"])
    return told


def escalate_overdue(limit: int = 200) -> int:
    """Beat task: climb one rung for every unacknowledged flag whose window has passed."""
    now = timezone.now()
    with transaction.atomic(), system_context():
        due = list(
            AnomalyFlag.objects.filter(status=FlagStatus.OPEN, sla_due_at__lte=now)
            .order_by("sla_due_at")
            .values_list("organization_id", "id")[:limit]
        )
    escalated = 0
    for organization_id, flag_id in due:
        with transaction.atomic():
            rls.set_tenant(organization_id)
            flag = (
                AnomalyFlag.objects.select_for_update(of=("self",))
                .select_related("polling_unit")
                .filter(id=flag_id, status=FlagStatus.OPEN, sla_due_at__lte=now)
                .first()
            )
            if flag is None:
                continue  # acknowledged or already escalated by another worker
            policy = matrix()[Severity(flag.severity)]
            target = next_level(Level(flag.escalation_level))
            if target is None:
                # Already at the top rung: nobody further to tell, so repeat the page
                # once on the louder channels, then stop the clock.
                flag.sla_due_at = None
                flag.save(update_fields=["sla_due_at", "updated_at"])
                FlagEvent.objects.create(
                    organization_id=flag.organization_id,
                    flag=flag,
                    action=FlagAction.ESCALATED,
                    from_status=flag.status,
                    to_status=flag.status,
                    details={"reminder": True, "level": flag.escalation_level},
                    at=now,
                )
                _tell(
                    flag,
                    [Level(flag.escalation_level)],
                    [*policy.channels, *policy.escalation_channels],
                    escalated=True,
                )
                escalated += 1
                continue
            before = flag.escalation_level
            flag.escalation_level = target
            minutes = policy.ack_minutes
            flag.sla_due_at = (
                now + timedelta(minutes=minutes) if minutes and target < Level.ADMIN else None
            )
            flag.save(update_fields=["escalation_level", "sla_due_at", "updated_at"])
            FlagEvent.objects.create(
                organization_id=flag.organization_id,
                flag=flag,
                action=FlagAction.ESCALATED,
                from_status=flag.status,
                to_status=flag.status,
                details={"from_level": before, "to_level": int(target)},
                at=now,
            )
            audit.record(
                action="anomaly.flag_escalated",
                object_type="anomaly_flag",
                object_id=flag.id,
                organization_id=flag.organization_id,
                diff={"from_level": before, "to_level": int(target), "severity": flag.severity},
            )
            channels = [*policy.channels, *policy.escalation_channels]
            _tell(flag, [target], dict.fromkeys(channels), escalated=True)
            escalated += 1
    return escalated
