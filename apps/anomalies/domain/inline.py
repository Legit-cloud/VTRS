"""Inline anomaly rules (spec section 13): cheap, deterministic checks run inside the submit
transaction. A finding never removes a result from the count; it routes it to review.

Contextual and statistical rules (GPS, timing, evidence, turnout outliers) run asynchronously
in `contextual.py`; they share the rule codes and severities declared here.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Severity(StrEnum):
    INFO = "INFO"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RuleCode(StrEnum):
    ARITHMETIC_VARIANCE = "ARITHMETIC_VARIANCE"  # FR-6.9.6
    OVER_VOTING = "OVER_VOTING"  # FR-6.9.2
    DUPLICATE_SOURCE = "DUPLICATE_SOURCE"  # FR-6.9.1
    VERSION_FORK = "VERSION_FORK"  # FR-6.9.1
    UNASSIGNED_PU_ATTEMPT = "UNASSIGNED_PU_ATTEMPT"  # FR-6.9.4
    LATE_SUBMISSION = "LATE_SUBMISSION"  # submitted after the election closed
    CONFIG_VERSION_MISMATCH = "CONFIG_VERSION_MISMATCH"
    # Contextual rules (FR-6.9.3 - FR-6.9.5)
    GPS_MISSING = "GPS_MISSING"
    GPS_OUT_OF_GEOFENCE = "GPS_OUT_OF_GEOFENCE"
    GPS_LOW_ACCURACY = "GPS_LOW_ACCURACY"
    DEVICE_CLOCK_AHEAD = "DEVICE_CLOCK_AHEAD"
    CAPTURED_BEFORE_POLLS_OPEN = "CAPTURED_BEFORE_POLLS_OPEN"
    CAPTURED_BEFORE_POLLS_CLOSE = "CAPTURED_BEFORE_POLLS_CLOSE"
    # Statistical rules (FR-6.9.2)
    TURNOUT_OUTLIER = "TURNOUT_OUTLIER"
    VOTE_SHARE_OUTLIER = "VOTE_SHARE_OUTLIER"
    HIGH_REJECTED_RATE = "HIGH_REJECTED_RATE"
    UNANIMOUS_RESULT = "UNANIMOUS_RESULT"
    # Evidence rules (FR-6.9.3)
    DUPLICATE_EVIDENCE = "DUPLICATE_EVIDENCE"
    EXIF_TIME_MISMATCH = "EXIF_TIME_MISMATCH"
    EXIF_GPS_MISMATCH = "EXIF_GPS_MISMATCH"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    EVIDENCE_QUARANTINED = "EVIDENCE_QUARANTINED"


SEVERITY: Mapping[RuleCode, Severity] = {
    RuleCode.ARITHMETIC_VARIANCE: Severity.HIGH,
    RuleCode.OVER_VOTING: Severity.CRITICAL,
    RuleCode.DUPLICATE_SOURCE: Severity.HIGH,
    RuleCode.VERSION_FORK: Severity.HIGH,
    RuleCode.UNASSIGNED_PU_ATTEMPT: Severity.CRITICAL,
    RuleCode.LATE_SUBMISSION: Severity.MEDIUM,
    RuleCode.CONFIG_VERSION_MISMATCH: Severity.MEDIUM,
    RuleCode.GPS_MISSING: Severity.MEDIUM,
    RuleCode.GPS_OUT_OF_GEOFENCE: Severity.MEDIUM,  # HIGH beyond the "far" distance
    RuleCode.GPS_LOW_ACCURACY: Severity.INFO,
    RuleCode.DEVICE_CLOCK_AHEAD: Severity.MEDIUM,
    RuleCode.CAPTURED_BEFORE_POLLS_OPEN: Severity.HIGH,
    RuleCode.CAPTURED_BEFORE_POLLS_CLOSE: Severity.HIGH,
    RuleCode.TURNOUT_OUTLIER: Severity.MEDIUM,  # HIGH at implausibly high turnout
    RuleCode.VOTE_SHARE_OUTLIER: Severity.MEDIUM,
    RuleCode.HIGH_REJECTED_RATE: Severity.MEDIUM,
    RuleCode.UNANIMOUS_RESULT: Severity.MEDIUM,
    RuleCode.DUPLICATE_EVIDENCE: Severity.HIGH,
    RuleCode.EXIF_TIME_MISMATCH: Severity.MEDIUM,
    RuleCode.EXIF_GPS_MISMATCH: Severity.MEDIUM,
    RuleCode.MISSING_EVIDENCE: Severity.MEDIUM,
    RuleCode.EVIDENCE_QUARANTINED: Severity.HIGH,
}


@dataclass(frozen=True)
class Finding:
    rule: RuleCode
    details: dict[str, Any] = field(default_factory=dict)
    # Set when a rule raises its own severity (e.g. a GPS fix kilometres away).
    severity_override: Severity | None = None

    @property
    def severity(self) -> Severity:
        return self.severity_override or SEVERITY[self.rule]


@dataclass(frozen=True)
class Totals:
    accredited: int | None
    valid: int
    rejected: int | None
    total_cast: int | None


def arithmetic(totals: Totals, votes: Mapping[Any, int]) -> list[Finding]:
    """The sheet's totals should reconcile: party votes + rejected = total votes cast.

    More than total cast is refused when the result is submitted. Less is accepted but flagged
    (FR-6.9.6): votes the sheet counts that are not recorded against any party."""
    party_votes = sum(votes.values())
    if totals.rejected is None or totals.total_cast is None:
        return []
    if party_votes + totals.rejected < totals.total_cast:
        return [
            Finding(
                RuleCode.ARITHMETIC_VARIANCE,
                {
                    "check": "party_votes_plus_rejected_vs_total_cast",
                    "party_votes": party_votes,
                    "rejected": totals.rejected,
                    "total_cast": totals.total_cast,
                },
            )
        ]
    return []


def over_voting(totals: Totals, registered_voters: int | None) -> list[Finding]:
    findings = []
    cast = totals.total_cast if totals.total_cast is not None else totals.valid
    if totals.accredited is not None and cast > totals.accredited:
        findings.append(
            Finding(
                RuleCode.OVER_VOTING,
                {"check": "cast_vs_accredited", "cast": cast, "accredited": totals.accredited},
            )
        )
    if (
        registered_voters is not None
        and totals.accredited is not None
        and totals.accredited > registered_voters
    ):
        findings.append(
            Finding(
                RuleCode.OVER_VOTING,
                {
                    "check": "accredited_vs_registered",
                    "accredited": totals.accredited,
                    "registered": registered_voters,
                },
            )
        )
    return findings


def merge(findings: list[Finding]) -> list[Finding]:
    """One flag per rule per version: combine the details of repeated findings."""
    by_rule: dict[RuleCode, list[dict[str, Any]]] = {}
    for finding in findings:
        by_rule.setdefault(finding.rule, []).append(finding.details)
    return [
        Finding(rule, details[0] if len(details) == 1 else {"checks": details})
        for rule, details in by_rule.items()
    ]
