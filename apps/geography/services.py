"""Master-data import (FR-6.4.1, FR-6.4.3). Idempotent: re-importing a file changes nothing."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from django.db import models, transaction

from apps.audit import services as audit
from apps.core.domain.actor import Actor

from .domain.master_data import Expectations, PollingUnitRow, ValidationReport, parse_and_validate
from .models import Lga, PollingUnit, State, Ward


@dataclass
class ImportOutcome:
    report: ValidationReport
    applied: bool = False
    changes: dict[str, dict[str, int]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"applied": self.applied, "changes": self.changes, **self.report.as_dict()}


GeoModel = type[State] | type[Lga] | type[Ward] | type[PollingUnit]


def _sync(model: GeoModel, desired: Mapping[str, dict[str, Any]]) -> dict[str, int]:
    existing = {o.inec_code: o for o in model.objects.filter(inec_code__in=list(desired))}
    to_create: list[models.Model] = []
    to_update: list[models.Model] = []
    for code, fields in desired.items():
        obj = existing.get(code)
        if obj is None:
            to_create.append(model(inec_code=code, **fields))
            continue
        changed = False
        for name, value in fields.items():
            if getattr(obj, name) != value:
                setattr(obj, name, value)
                changed = True
        if changed:
            to_update.append(obj)
    manager: Any = model.objects
    manager.bulk_create(to_create, batch_size=1000)
    if to_update:
        manager.bulk_update(to_update, fields=list(next(iter(desired.values()))), batch_size=1000)
    return {"created": len(to_create), "updated": len(to_update)}


def _ids(model: GeoModel, codes: Iterable[str]) -> dict[str, Any]:
    return dict(model.objects.filter(inec_code__in=list(codes)).values_list("inec_code", "id"))


def _apply(rows: list[PollingUnitRow]) -> dict[str, dict[str, int]]:
    changes = {}
    changes["states"] = _sync(State, {r.state_code: {"name": r.state_name} for r in rows})
    state_ids = _ids(State, {r.state_code for r in rows})

    changes["lgas"] = _sync(
        Lga, {r.lga_code: {"name": r.lga_name, "state_id": state_ids[r.state_code]} for r in rows}
    )
    lga_ids = _ids(Lga, {r.lga_code for r in rows})

    changes["wards"] = _sync(
        Ward,
        {
            r.ward_code: {
                "name": r.ward_name,
                "lga_id": lga_ids[r.lga_code],
                "state_id": state_ids[r.state_code],
            }
            for r in rows
        },
    )
    ward_ids = _ids(Ward, {r.ward_code for r in rows})

    changes["polling_units"] = _sync(
        PollingUnit,
        {
            r.pu_code: {
                "name": r.pu_name,
                "ward_id": ward_ids[r.ward_code],
                "lga_id": lga_ids[r.lga_code],
                "state_id": state_ids[r.state_code],
                "latitude": r.latitude,
                "longitude": r.longitude,
                "registered_voters": r.registered_voters,
            }
            for r in rows
        },
    )
    return changes


def import_master_data(
    records: Iterable[Mapping[str, str]],
    *,
    expectations: Expectations | None = None,
    actor: Actor | None = None,
    dry_run: bool = False,
) -> ImportOutcome:
    """Validate the dataset and, if it is clean, upsert it in one audited transaction.

    Polling units missing from the file are reported, never deleted: results may reference them.
    """
    report = parse_and_validate(records, expectations)
    outcome = ImportOutcome(report=report)
    if not report.ok:
        return outcome

    codes = [r.pu_code for r in report.rows]
    not_in_file = PollingUnit.objects.exclude(inec_code__in=codes).count()
    if not_in_file:
        report.warnings.append(f"{not_in_file} polling units in the database are not in this file")
    if dry_run:
        return outcome

    with transaction.atomic():
        outcome.changes = _apply(report.rows)
        outcome.applied = True
        audit.record(
            action="geography.master_data_imported",
            object_type="geography",
            object_id=",".join(sorted({r.state_code for r in report.rows}))[:64],
            actor=actor,
            diff={"counts": report.counts, "changes": outcome.changes},
        )
    return outcome
