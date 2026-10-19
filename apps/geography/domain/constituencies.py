"""Election types and constituency delimitation (FR-6.3.1, FR-6.3.6, FR-6.4.5).

An election type names the constituency kind its races are held in. A constituency file maps
whole LGAs or whole wards to constituencies of one kind; every polling unit inside them then
belongs to that constituency. Validation is pure: it produces a report and never touches the
database. Errors block an import; warnings do not.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

# Kinds that follow the geography one to one and are derived from it, never imported.
DERIVED_KINDS = ("STATE", "LGA", "WARD")
CONSTITUENCY_COLUMNS = ("kind", "code", "name", "state_code", "lga_code")
OPTIONAL_CONSTITUENCY_COLUMNS = ("ward_code",)
MAX_LISTED_ERRORS = 200


@dataclass(frozen=True, slots=True)
class ElectionTypeRow:
    code: str
    name: str
    constituency_kind: str
    sort_order: int


def parse_election_types(raw: Iterable[Mapping[str, Any]]) -> list[ElectionTypeRow]:
    """Validate the election type configuration; raises ValueError with every problem found."""
    rows, problems, seen = [], [], set()
    for index, entry in enumerate(raw, start=1):
        code = str(entry.get("code", "")).strip().upper()
        name = str(entry.get("name", "")).strip()
        kind = str(entry.get("constituency_kind", "")).strip().upper()
        if not code or not name or not kind:
            problems.append(f"entry {index}: code, name and constituency_kind are required")
            continue
        if code in seen:
            problems.append(f"entry {index}: code {code} repeats")
            continue
        seen.add(code)
        try:
            order = int(entry.get("sort_order", index * 10))
        except (TypeError, ValueError):
            problems.append(f"entry {index}: sort_order must be a whole number")
            continue
        rows.append(ElectionTypeRow(code, name, kind, order))
    if not rows and not problems:
        problems.append("no election types given")
    if problems:
        raise ValueError("; ".join(problems))
    return rows


@dataclass(frozen=True, slots=True)
class ConstituencyRow:
    line: int
    kind: str
    code: str
    name: str
    state_code: str
    lga_code: str
    ward_code: str  # empty: the whole LGA


@dataclass
class ConstituencyReport:
    rows: list[ConstituencyRow] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error_count: int = 0

    @property
    def ok(self) -> bool:
        return self.error_count == 0

    def error(self, message: str) -> None:
        self.error_count += 1
        if len(self.errors) < MAX_LISTED_ERRORS:
            self.errors.append(message)

    def as_dict(self) -> dict[str, Any]:
        kinds: dict[str, set[str]] = {}
        for row in self.rows:
            kinds.setdefault(row.kind, set()).add(row.code)
        return {
            "ok": self.ok,
            "constituencies": {kind: len(codes) for kind, codes in sorted(kinds.items())},
            "rows": len(self.rows),
            "error_count": self.error_count,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def parse_constituencies(
    records: Iterable[Mapping[str, str]],
    *,
    lga_states: Mapping[str, str],
    ward_lgas: Mapping[str, str],
) -> ConstituencyReport:
    """Check a constituency file against known geography codes.

    `lga_states` maps LGA code -> state code and `ward_lgas` maps ward code -> LGA code, for the
    geography already imported. Each LGA or ward may be claimed by one constituency per kind,
    and an LGA cannot be claimed whole and ward by ward for the same kind.
    """
    report = ConstituencyReport()
    identity: dict[tuple[str, str], tuple[str, str]] = {}
    whole_lgas: dict[tuple[str, str], str] = {}
    wards: dict[tuple[str, str], str] = {}
    lgas_split: dict[tuple[str, str], str] = {}

    for line, record in enumerate(records, start=2):
        values = {k: (record.get(k) or "").strip() for k in (*CONSTITUENCY_COLUMNS, "ward_code")}
        missing = [k for k in CONSTITUENCY_COLUMNS if not values[k]]
        if missing:
            report.error(f"line {line}: missing {', '.join(missing)}")
            continue
        kind = values["kind"].upper()
        if kind in DERIVED_KINDS:
            report.error(f"line {line}: {kind} constituencies are derived from geography")
            continue
        code, state, lga, ward = (
            values["code"],
            values["state_code"],
            values["lga_code"],
            values["ward_code"],
        )
        if lga_states.get(lga) != state:
            report.error(f"line {line}: LGA {lga} is unknown or not in state {state}")
            continue
        if ward and ward_lgas.get(ward) != lga:
            report.error(f"line {line}: ward {ward} is unknown or not in LGA {lga}")
            continue
        named = identity.setdefault((kind, code), (values["name"], state))
        if named != (values["name"], state):
            report.error(f"line {line}: {kind} {code} is given two names or states")
            continue
        if ward:
            if (owner := wards.get((kind, ward))) is not None and owner != code:
                report.error(f"line {line}: ward {ward} is already in {kind} {owner}")
                continue
            if (kind, lga) in whole_lgas:
                report.error(f"line {line}: LGA {lga} is already wholly in {kind}")
                continue
            wards[(kind, ward)] = code
            lgas_split[(kind, lga)] = code
        else:
            if (owner := whole_lgas.get((kind, lga))) is not None and owner != code:
                report.error(f"line {line}: LGA {lga} is already in {kind} {owner}")
                continue
            if (kind, lga) in lgas_split:
                report.error(f"line {line}: LGA {lga} is already split by ward for {kind}")
                continue
            whole_lgas[(kind, lga)] = code
        report.rows.append(ConstituencyRow(line, kind, code, values["name"], state, lga, ward))

    if not report.rows and report.ok:
        report.error("the file has no rows")
    return report
