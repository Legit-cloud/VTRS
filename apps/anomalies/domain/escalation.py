"""Alert routing and escalation (FR-6.9.7, PB-10).

The matrix follows the usual incident-severity model: how loudly we tell people, who is told
first, how long they have to acknowledge, and who hears next if nobody does. It is data, so the
operations team can change it in settings without a code change.

Levels are rungs of the chain of command, not roles: WARD -> LGA -> ADMIN. A recipient at a
level is the person whose geography covers the flag at that rung (the ward officer of that
ward, the LGA officer of that LGA, the organization's admins).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import IntEnum, StrEnum
from typing import Any

from .inline import Severity


class Level(IntEnum):
    WARD = 0
    LGA = 1
    ADMIN = 2


class Channel(StrEnum):
    IN_APP = "IN_APP"
    PUSH = "PUSH"
    SMS = "SMS"
    EMAIL = "EMAIL"
    WHATSAPP = "WHATSAPP"


@dataclass(frozen=True, slots=True)
class Policy:
    """How one severity is handled."""

    # Levels told the moment the flag is raised.
    notify: tuple[Level, ...]
    channels: tuple[Channel, ...]
    # Minutes before an unacknowledged flag climbs one level; None means it never escalates.
    ack_minutes: int | None
    # Channels added when the flag escalates (a flag nobody answered deserves a louder voice).
    escalation_channels: tuple[Channel, ...] = ()


DEFAULT_MATRIX: Mapping[Severity, Policy] = {
    # P1: possible fraud or impossible numbers. Everyone up the chain, now, on every channel.
    Severity.CRITICAL: Policy(
        notify=(Level.WARD, Level.LGA, Level.ADMIN),
        channels=(Channel.IN_APP, Channel.SMS, Channel.EMAIL),
        ack_minutes=15,
        escalation_channels=(Channel.WHATSAPP,),
    ),
    # P2: needs a decision today. The ward and LGA are told; the admin hears if it sits.
    Severity.HIGH: Policy(
        notify=(Level.WARD, Level.LGA),
        channels=(Channel.IN_APP, Channel.EMAIL),
        ack_minutes=30,
        escalation_channels=(Channel.SMS,),
    ),
    # P3: a reviewer's queue item. The ward looks first; the LGA after two hours.
    Severity.MEDIUM: Policy(
        notify=(Level.WARD,),
        channels=(Channel.IN_APP,),
        ack_minutes=120,
        escalation_channels=(Channel.EMAIL,),
    ),
    # P4: information for the record. Listed, never pushed, never escalated.
    Severity.INFO: Policy(notify=(), channels=(), ack_minutes=None),
}


def matrix_from_settings(
    raw: Mapping[str, Mapping[str, Any]] | None,
) -> Mapping[Severity, Policy]:
    """Build the matrix from settings; missing severities keep their defaults."""
    if not raw:
        return DEFAULT_MATRIX
    merged = dict(DEFAULT_MATRIX)
    for name, cfg in raw.items():
        severity = Severity(name)
        base = merged[severity]
        notify: Sequence[str] = cfg.get("notify", [lv.name for lv in base.notify])
        channels: Sequence[str] = cfg.get("channels", [c.value for c in base.channels])
        escalation: Sequence[str] = cfg.get(
            "escalation_channels", [c.value for c in base.escalation_channels]
        )
        merged[severity] = Policy(
            notify=tuple(Level[x] for x in notify),
            channels=tuple(Channel(x) for x in channels),
            ack_minutes=cfg.get("ack_minutes", base.ack_minutes),
            escalation_channels=tuple(Channel(x) for x in escalation),
        )
    return merged


def top_level(policy: Policy) -> Level:
    return max(policy.notify, default=Level.WARD)


def initial_due(policy: Policy, raised_at: datetime) -> datetime | None:
    if policy.ack_minutes is None or not policy.notify:
        return None
    return raised_at + timedelta(minutes=policy.ack_minutes)


def next_level(current: Level) -> Level | None:
    return Level(current + 1) if current < Level.ADMIN else None


def levels_to_notify(policy: Policy) -> Sequence[Level]:
    return policy.notify


def is_overdue(due_at: datetime | None, now: datetime) -> bool:
    return due_at is not None and due_at <= now
