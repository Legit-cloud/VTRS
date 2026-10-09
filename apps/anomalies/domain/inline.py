"""Inline anomaly rules (spec section 13): cheap, deterministic checks run inside the submit
transaction. A finding never removes a result from the count; it routes it to review.

Contextual and statistical rules (GPS, timing, evidence, turnout outliers) run asynchronously
and arrive with M5.
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
    LATE_SUBMISSION = "LATE_SUBMISSION"  # captured offline, synced after polls closed
    CONFIG_VERSION_MISMATCH = "CONFIG_VERSION_MISMATCH"


SEVERITY: Mapping[RuleCode, Severity] = {
    RuleCode.ARITHMETIC_VARIANCE: Severity.HIGH,
    RuleCode.OVER_VOTING: Severity.CRITICAL,
    RuleCode.DUPLICATE_SOURCE: Severity.HIGH,
    RuleCode.VERSION_FORK: Severity.HIGH,
    RuleCode.UNASSIGNED_PU_ATTEMPT: Severity.CRITICAL,
    RuleCode.LATE_SUBMISSION: Severity.MEDIUM,
    RuleCode.CONFIG_VERSION_MISMATCH: Severity.MEDIUM,
}


@dataclass(frozen=True)
class Finding:
    rule: RuleCode
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def severity(self) -> Severity:
        return SEVERITY[self.rule]


@dataclass(frozen=True)
class Totals:
    accredited: int | None
    valid: int
    rejected: int | None
    total_cast: int | None


def arithmetic(totals: Totals, votes: Mapping[Any, int]) -> list[Finding]:
    findings = []
    candidate_sum = sum(votes.values())
    if candidate_sum != totals.valid:
        findings.append(
            Finding(
                RuleCode.ARITHMETIC_VARIANCE,
                {"check": "candidate_votes_vs_valid", "sum": candidate_sum, "valid": totals.valid},
            )
        )
    if totals.rejected is not None and totals.total_cast is not None:
        if totals.valid + totals.rejected != totals.total_cast:
            findings.append(
                Finding(
                    RuleCode.ARITHMETIC_VARIANCE,
                    {
                        "check": "valid_plus_rejected_vs_total_cast",
                        "valid": totals.valid,
                        "rejected": totals.rejected,
                        "total_cast": totals.total_cast,
                    },
                )
            )
    return findings


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
