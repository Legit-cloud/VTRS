"""Master-data import (FR-6.4.1, FR-6.4.3). Idempotent: re-importing a file changes nothing."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from django.db import models, transaction

from apps.audit import services as audit
from apps.core.domain.actor import Actor

from .domain.constituencies import ConstituencyReport, parse_constituencies, parse_election_types
from .domain.master_data import Expectations, PollingUnitRow, ValidationReport, parse_and_validate
from .models import (
    Constituency,
    ElectionType,
    Lga,
    PollingUnit,
    PollingUnitConstituency,
    State,
    Ward,
)


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


class _Discard(Exception):
    """Raised to roll a preview back; never leaves this module."""


def preview_master_data(
    records: Iterable[Mapping[str, str]], *, expectations: Expectations | None = None
) -> ImportOutcome:
    """What an import would change: how many rows it would add and update.

    The changes are computed by applying them inside a savepoint and rolling it back, so the
    numbers are exactly what the real import would produce, with nothing written.
    """
    outcome = import_master_data(records, expectations=expectations, dry_run=True)
    if not outcome.report.ok:
        return outcome
    try:
        with transaction.atomic():
            outcome.changes = _apply(outcome.report.rows)
            raise _Discard
    except _Discard:
        pass
    return outcome


# --- Election types and constituencies (FR-6.3.6, FR-6.4.5) ----------------------------------


def load_election_types(
    entries: Iterable[Mapping[str, Any]], *, actor: Actor | None = None
) -> dict[str, int]:
    """Upsert the configured election types. Types missing from the file are deactivated, never
    deleted: elections may reference them."""
    rows = parse_election_types(entries)
    with transaction.atomic():
        existing = {t.code: t for t in ElectionType.objects.all()}
        created = updated = 0
        for row in rows:
            fields = {
                "name": row.name,
                "constituency_kind": row.constituency_kind,
                "sort_order": row.sort_order,
                "is_active": True,
            }
            current = existing.get(row.code)
            if current is None:
                ElectionType.objects.create(code=row.code, **fields)
                created += 1
            elif any(getattr(current, k) != v for k, v in fields.items()):
                ElectionType.objects.filter(id=current.id).update(**fields)
                updated += 1
        deactivated = (
            ElectionType.objects.exclude(code__in=[r.code for r in rows])
            .filter(is_active=True)
            .update(is_active=False)
        )
        changes = {"created": created, "updated": updated, "deactivated": deactivated}
        audit.record(
            action="geography.election_types_loaded",
            object_type="election_type",
            object_id="all",
            actor=actor,
            diff=changes,
        )
    return changes


def _map_units(kind: str, units: Mapping[Any, Any]) -> int:
    """Point each polling unit (id -> constituency id) at its constituency for one kind."""
    existing = dict(
        PollingUnitConstituency.objects.filter(
            kind=kind, polling_unit_id__in=list(units)
        ).values_list("polling_unit_id", "constituency_id")
    )
    stale = [pu for pu, c in units.items() if pu in existing and existing[pu] != c]
    PollingUnitConstituency.objects.filter(kind=kind, polling_unit_id__in=stale).delete()
    fresh = [
        PollingUnitConstituency(polling_unit_id=pu, kind=kind, constituency_id=c)
        for pu, c in units.items()
        if existing.get(pu) != c
    ]
    PollingUnitConstituency.objects.bulk_create(fresh, batch_size=2000)
    return len(fresh)


def _upsert_constituencies(kind: str, wanted: Mapping[str, tuple[str, Any]]) -> dict[str, Any]:
    """code -> (name, state id); returns code -> constituency id."""
    existing = {c.code: c for c in Constituency.objects.filter(kind=kind, code__in=list(wanted))}
    for code, (name, state_id) in wanted.items():
        current = existing.get(code)
        if current is None:
            existing[code] = Constituency.objects.create(
                kind=kind, code=code, name=name, state_id=state_id
            )
        elif (current.name, current.state_id) != (name, state_id):
            Constituency.objects.filter(id=current.id).update(name=name, state_id=state_id)
    return {code: c.id for code, c in existing.items()}


def derive_constituencies(*, actor: Actor | None = None) -> dict[str, int]:
    """One STATE, LGA and WARD constituency per state, LGA and ward, with every unit mapped.
    Idempotent; run again after a master-data import."""
    mapped: dict[str, int] = {}
    with transaction.atomic():
        states = list(State.objects.all())
        lgas = list(Lga.objects.all())
        wards = list(Ward.objects.all())
        levels: list[tuple[str, dict[str, tuple[str, Any]], dict[Any, str], str]] = [
            (
                "STATE",
                {s.inec_code: (s.name, s.id) for s in states},
                {s.id: s.inec_code for s in states},
                "state_id",
            ),
            (
                "LGA",
                {a.inec_code: (a.name, a.state_id) for a in lgas},
                {a.id: a.inec_code for a in lgas},
                "lga_id",
            ),
            (
                "WARD",
                {w.inec_code: (w.name, w.state_id) for w in wards},
                {w.id: w.inec_code for w in wards},
                "ward_id",
            ),
        ]
        for kind, wanted, codes, unit_field in levels:
            ids = _upsert_constituencies(kind, wanted)
            units = {
                pu: ids[codes[area]]
                for pu, area in PollingUnit.objects.values_list("id", unit_field).iterator()
            }
            mapped[kind] = _map_units(kind, units)
        audit.record(
            action="geography.constituencies_derived",
            object_type="constituency",
            object_id="derived",
            actor=actor,
            diff={"mapped": mapped},
        )
    return mapped


@dataclass
class ConstituencyImport:
    report: ConstituencyReport
    applied: bool = False
    mapped: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"applied": self.applied, "mapped": self.mapped, **self.report.as_dict()}


def import_constituencies(
    records: Iterable[Mapping[str, str]], *, actor: Actor | None = None, dry_run: bool = False
) -> ConstituencyImport:
    """Validate a delimitation file and, if clean, upsert it in one audited transaction.

    Every polling unit of the LGAs and wards named is mapped; units of the same states left
    without a constituency of an imported kind are reported as warnings."""
    report = parse_constituencies(
        records,
        lga_states=dict(Lga.objects.values_list("inec_code", "state__inec_code")),
        ward_lgas=dict(Ward.objects.values_list("inec_code", "lga__inec_code")),
    )
    outcome = ConstituencyImport(report=report)
    if not report.ok:
        return outcome

    lga_ids = dict(Lga.objects.values_list("inec_code", "id"))
    ward_ids = dict(Ward.objects.values_list("inec_code", "id"))
    state_ids = dict(State.objects.values_list("inec_code", "id"))
    kinds = sorted({r.kind for r in report.rows})
    states = {state_ids[r.state_code] for r in report.rows}
    for kind in kinds:
        whole = {lga_ids[r.lga_code] for r in report.rows if r.kind == kind and not r.ward_code}
        split = {ward_ids[r.ward_code] for r in report.rows if r.kind == kind and r.ward_code}
        missed = (
            PollingUnit.objects.filter(state_id__in=states)
            .exclude(lga_id__in=whole)
            .exclude(ward_id__in=split)
            .count()
        )
        if missed:
            report.warnings.append(f"{missed} polling units have no {kind} constituency")
    if dry_run:
        return outcome

    with transaction.atomic():
        for kind in kinds:
            rows = [r for r in report.rows if r.kind == kind]
            ids = _upsert_constituencies(
                kind, {r.code: (r.name, state_ids[r.state_code]) for r in rows}
            )
            units: dict[Any, Any] = {}
            for row in rows:
                if row.ward_code:
                    area = PollingUnit.objects.filter(ward_id=ward_ids[row.ward_code])
                else:
                    area = PollingUnit.objects.filter(lga_id=lga_ids[row.lga_code])
                for pu in area.values_list("id", flat=True):
                    units[pu] = ids[row.code]
            outcome.mapped[kind] = _map_units(kind, units)
        outcome.applied = True
        audit.record(
            action="geography.constituencies_imported",
            object_type="constituency",
            object_id=",".join(kinds)[:64],
            actor=actor,
            diff={"summary": report.as_dict()["constituencies"], "mapped": outcome.mapped},
        )
    return outcome
