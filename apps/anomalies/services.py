"""Raising flags. Called inside the caller's transaction (inline rules run in the submit)."""

from typing import Any

from apps.audit import services as audit
from apps.core.domain.canonical import to_json_compatible

from .domain.inline import Finding
from .models import AnomalyFlag


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
    return flags
