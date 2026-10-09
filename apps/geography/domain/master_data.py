"""Parse and validate a polling-unit master dataset (FR-6.4.1 - FR-6.4.4).

One row per polling unit, carrying its ward, LGA and state. Validation is pure: it produces a
report and never touches the database. Errors block an import; warnings do not.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

REQUIRED_COLUMNS = (
    "state_code",
    "state_name",
    "lga_code",
    "lga_name",
    "ward_code",
    "ward_name",
    "pu_code",
    "pu_name",
)
OPTIONAL_COLUMNS = ("latitude", "longitude", "registered_voters")
# Generous bounding box for Nigeria; anything outside is a data error.
NIGERIA_LAT = (Decimal("4.0"), Decimal("14.0"))
NIGERIA_LNG = (Decimal("2.5"), Decimal("15.0"))
_SIX_PLACES = Decimal("0.000001")
MAX_LISTED_ERRORS = 200


@dataclass(frozen=True, slots=True)
class PollingUnitRow:
    line: int
    state_code: str
    state_name: str
    lga_code: str
    lga_name: str
    ward_code: str
    ward_name: str
    pu_code: str
    pu_name: str
    latitude: Decimal | None
    longitude: Decimal | None
    registered_voters: int | None


@dataclass(frozen=True, slots=True)
class Expectations:
    lgas: int | None = None
    wards: int | None = None
    polling_units: int | None = None
    polling_unit_tolerance: float = 0.0

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "Expectations":
        return cls(
            lgas=values.get("lgas"),
            wards=values.get("wards"),
            polling_units=values.get("polling_units"),
            polling_unit_tolerance=float(values.get("polling_unit_tolerance", 0.0)),
        )


@dataclass
class ValidationReport:
    rows: list[PollingUnitRow] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    error_count: int = 0
    warnings: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    coordinate_coverage: float = 0.0

    @property
    def ok(self) -> bool:
        return self.error_count == 0

    def error(self, message: str) -> None:
        self.error_count += 1
        if len(self.errors) < MAX_LISTED_ERRORS:
            self.errors.append(message)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "counts": self.counts,
            "coordinate_coverage": round(self.coordinate_coverage, 4),
            "error_count": self.error_count,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def _parse_decimal(raw: str) -> Decimal | None:
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    return value.quantize(_SIX_PLACES) if value.is_finite() else None


def _parse_row(
    line: int, record: Mapping[str, str], report: ValidationReport
) -> PollingUnitRow | None:
    values = {k: (record.get(k) or "").strip() for k in REQUIRED_COLUMNS + OPTIONAL_COLUMNS}
    missing = [k for k in REQUIRED_COLUMNS if not values[k]]
    if missing:
        report.error(f"line {line}: missing {', '.join(missing)}")
        return None

    latitude = longitude = None
    lat_raw, lng_raw = values["latitude"], values["longitude"]
    if bool(lat_raw) != bool(lng_raw):
        report.error(f"line {line}: latitude and longitude must both be present or both empty")
        return None
    if lat_raw:
        latitude, longitude = _parse_decimal(lat_raw), _parse_decimal(lng_raw)
        if latitude is None or longitude is None:
            report.error(f"line {line}: coordinates are not numbers")
            return None
        if not (NIGERIA_LAT[0] <= latitude <= NIGERIA_LAT[1]) or not (
            NIGERIA_LNG[0] <= longitude <= NIGERIA_LNG[1]
        ):
            report.error(f"line {line}: coordinates {latitude},{longitude} are outside Nigeria")
            return None

    registered = None
    if values["registered_voters"]:
        try:
            registered = int(values["registered_voters"])
        except ValueError:
            registered = -1
        if registered < 0:
            report.error(f"line {line}: registered_voters must be a whole number >= 0")
            return None

    return PollingUnitRow(
        line=line,
        state_code=values["state_code"],
        state_name=values["state_name"],
        lga_code=values["lga_code"],
        lga_name=values["lga_name"],
        ward_code=values["ward_code"],
        ward_name=values["ward_name"],
        pu_code=values["pu_code"],
        pu_name=values["pu_name"],
        latitude=latitude,
        longitude=longitude,
        registered_voters=registered,
    )


class _ParentIndex:
    """Checks that each code always has the same parent and name."""

    def __init__(self, level: str, report: ValidationReport) -> None:
        self.level = level
        self.report = report
        self.seen: dict[str, tuple[str, str]] = {}
        self.reported: set[str] = set()

    def add(self, line: int, code: str, parent: str, name: str) -> None:
        known = self.seen.setdefault(code, (parent, name))
        if known != (parent, name) and code not in self.reported:
            self.reported.add(code)
            self.report.error(
                f"line {line}: {self.level} {code} conflicts with an earlier row "
                f"(parent/name {known[0]}/{known[1]} vs {parent}/{name})"
            )


def parse_and_validate(
    records: Iterable[Mapping[str, str]], expectations: Expectations | None = None
) -> ValidationReport:
    report = ValidationReport()
    states = _ParentIndex("state", report)
    lgas = _ParentIndex("LGA", report)
    wards = _ParentIndex("ward", report)
    first_line_for_pu: dict[str, int] = {}

    for line, record in enumerate(records, start=2):  # line 1 is the header
        row = _parse_row(line, record, report)
        if row is None:
            continue
        if row.pu_code in first_line_for_pu:
            report.error(
                f"line {line}: polling unit {row.pu_code} duplicates line "
                f"{first_line_for_pu[row.pu_code]}"
            )
            continue
        first_line_for_pu[row.pu_code] = line
        states.add(line, row.state_code, "", row.state_name)
        lgas.add(line, row.lga_code, row.state_code, row.lga_name)
        wards.add(line, row.ward_code, row.lga_code, row.ward_name)
        report.rows.append(row)

    if not report.rows and report.error_count == 0:
        report.error("the dataset has no rows")

    report.counts = {
        "states": len(states.seen),
        "lgas": len(lgas.seen),
        "wards": len(wards.seen),
        "polling_units": len(report.rows),
    }
    with_coordinates = sum(1 for r in report.rows if r.latitude is not None)
    report.coordinate_coverage = with_coordinates / len(report.rows) if report.rows else 0.0
    if report.rows and with_coordinates < len(report.rows):
        report.warnings.append(
            f"{len(report.rows) - with_coordinates} polling units have no coordinates; "
            "GPS rules for them are informational only"
        )

    if expectations:
        _check_expectations(report, expectations)
    return report


def _check_expectations(report: ValidationReport, expected: Expectations) -> None:
    counts = report.counts
    if expected.lgas is not None and counts["lgas"] != expected.lgas:
        report.error(f"expected {expected.lgas} LGAs, found {counts['lgas']}")
    if expected.wards is not None and counts["wards"] != expected.wards:
        report.error(f"expected {expected.wards} wards, found {counts['wards']}")
    if expected.polling_units is not None:
        allowed = expected.polling_units * expected.polling_unit_tolerance
        if abs(counts["polling_units"] - expected.polling_units) > allowed:
            report.error(
                f"expected about {expected.polling_units} polling units "
                f"(tolerance {expected.polling_unit_tolerance:.0%}), "
                f"found {counts['polling_units']}"
            )
