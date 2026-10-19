"""Export hygiene: cell safety and file names (FR-6.10.5, spec section 14).

Exports are opened in spreadsheet programs by people who trust them, so any text that a
spreadsheet would treat as a formula is neutralized, whoever supplied it (agent names, polling
unit names, flag notes).
"""

import re
from collections.abc import Iterable, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Any

# What starts a formula in Excel, LibreOffice and Google Sheets, plus control characters that
# some programs strip before evaluating.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")

PROVISIONAL_FILE_TAG = "PROVISIONAL"


class ExportKind(StrEnum):
    RESULTS = "RESULTS"
    FLAGS = "FLAGS"
    AUDIT = "AUDIT"
    EVIDENCE_PACK = "EVIDENCE_PACK"


class ExportFormat(StrEnum):
    CSV = "CSV"
    XLSX = "XLSX"
    ZIP = "ZIP"


ALLOWED_FORMATS: dict[ExportKind, tuple[ExportFormat, ...]] = {
    ExportKind.RESULTS: (ExportFormat.CSV, ExportFormat.XLSX),
    ExportKind.FLAGS: (ExportFormat.CSV, ExportFormat.XLSX),
    ExportKind.AUDIT: (ExportFormat.CSV,),
    ExportKind.EVIDENCE_PACK: (ExportFormat.ZIP,),
}

EXTENSIONS = {ExportFormat.CSV: "csv", ExportFormat.XLSX: "xlsx", ExportFormat.ZIP: "zip"}
CONTENT_TYPES = {
    ExportFormat.CSV: "text/csv",
    ExportFormat.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ExportFormat.ZIP: "application/zip",
}


def safe_cell(value: Any) -> Any:
    """Text that would be read as a formula gets a leading apostrophe; other values pass."""
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def safe_row(values: Iterable[Any]) -> list[Any]:
    return [safe_cell(v) for v in values]


_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def slug(text: str, limit: int = 40) -> str:
    """A string that is safe in a file name and in a path inside an archive."""
    cleaned = _UNSAFE.sub("-", text).strip("-.")
    return (cleaned or "x")[:limit]


def export_filename(kind: ExportKind, label: str, at: datetime, fmt: ExportFormat) -> str:
    stamp = at.strftime("%Y%m%dT%H%M%SZ")
    tag = (
        f"-{PROVISIONAL_FILE_TAG}" if kind in {ExportKind.RESULTS, ExportKind.EVIDENCE_PACK} else ""
    )
    return f"vtrs-{kind.value.lower()}-{slug(label)}-{stamp}{tag}.{EXTENSIONS[fmt]}"


def columns_for_candidates(base: Sequence[str], acronyms: Sequence[str]) -> list[str]:
    """Result columns with one `votes_<party>` column per contesting party, in ballot order."""
    return [*base, *(f"votes_{slug(a, 20)}" for a in acronyms)]
