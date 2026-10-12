"""Convert a names-only polling-unit directory (Markdown) into master-data rows.

The community directory lists State > LGA > Ward > Polling Unit by name, in document order,
with no INEC codes. The importer needs a stable code per level, so provisional codes are
derived from position and prefixed ``DIR`` so they can never be mistaken for INEC codes. The
rows carry no coordinates or voter counts; both columns are left empty.

Positional codes are only stable while the source file is unchanged. They are placeholders
until an INEC export is imported (PB-03).
"""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

_LGA = re.compile(r"^## (?P<name>.+?)\s+LGA\s*$")
_WARD = re.compile(r"^### (?P<name>.+?)\s+Ward\s+\((?P<count>\d+) PUs\)\s*$")
_UNIT = re.compile(r"^\d+\.\s+(?P<name>.+?)\s*$")


class DirectoryFormatError(ValueError):
    """The Markdown is not shaped like the directory (always carries the line number)."""


@dataclass(frozen=True, slots=True)
class DirectoryStats:
    lgas: int
    wards: int
    polling_units: int


def parse_directory(
    lines: Iterable[str], *, state_code: str, state_name: str
) -> Iterator[dict[str, str]]:
    """Yield one master-data row per polling unit, in document order.

    Raises ``DirectoryFormatError`` for a polling unit outside a ward, a ward outside an LGA, or
    a ward whose declared count differs from the units listed under it."""
    prefix = f"DIR-{state_code}"
    lga_no = ward_no = pu_no = 0
    lga_name = ward_name = ""
    declared = 0
    open_ward_line = 0

    def close_ward() -> None:
        if ward_name and pu_no != declared:
            raise DirectoryFormatError(
                f"line {open_ward_line}: ward '{ward_name}' declares {declared} polling units "
                f"but lists {pu_no}"
            )

    for number, raw in enumerate(lines, start=1):
        line = raw.rstrip("\r\n")
        if lga := _LGA.match(line):
            close_ward()
            lga_no, ward_no, pu_no, ward_name, declared = lga_no + 1, 0, 0, "", 0
            lga_name = lga["name"]
        elif ward := _WARD.match(line):
            close_ward()
            if not lga_name:
                raise DirectoryFormatError(
                    f"line {number}: ward '{ward['name']}' is outside an LGA"
                )
            ward_no, pu_no = ward_no + 1, 0
            ward_name, declared, open_ward_line = ward["name"], int(ward["count"]), number
        elif unit := _UNIT.match(line):
            if not ward_name:
                raise DirectoryFormatError(f"line {number}: polling unit is outside a ward")
            pu_no += 1
            lga_code = f"{prefix}-{lga_no:02d}"
            ward_code = f"{lga_code}-{ward_no:03d}"
            yield {
                "state_code": prefix,
                "state_name": state_name,
                "lga_code": lga_code,
                "lga_name": lga_name,
                "ward_code": ward_code,
                "ward_name": ward_name,
                "pu_code": f"{ward_code}-{pu_no:03d}",
                "pu_name": unit["name"],
                "latitude": "",
                "longitude": "",
                "registered_voters": "",
            }
    close_ward()
