"""Export hygiene as pure functions (FR-6.10.5)."""

from datetime import UTC, datetime

import pytest

from apps.reports.domain.formats import (
    ALLOWED_FORMATS,
    ExportFormat,
    ExportKind,
    columns_for_candidates,
    export_filename,
    safe_cell,
    safe_row,
    slug,
)
from apps.reports.domain.pack import VERIFY_SCRIPT, evidence_path


@pytest.mark.parametrize("text", ["=1+1", "+cmd", "-2+3", "@SUM(A1)", "\t=1", "\r\n=1"])
def test_formula_like_text_is_neutralized(text):
    assert safe_cell(text) == "'" + text


@pytest.mark.parametrize("value", ["Ward 4", "", "a=b", 12, -7, 3.5, None])
def test_everything_else_is_left_alone(value):
    assert safe_cell(value) == value


def test_rows_are_cleaned_cell_by_cell():
    assert safe_row(["ok", "=evil()", 5]) == ["ok", "'=evil()", 5]


def test_slugs_are_safe_in_paths():
    assert slug("../../etc/passwd") == "etc-passwd"
    assert slug("Governor / Oyo State") == "Governor-Oyo-State"
    assert slug("") == "x"
    assert len(slug("a" * 200)) == 40


def test_filenames_carry_the_provisional_tag_for_results():
    at = datetime(2027, 3, 12, 9, 30, 5, tzinfo=UTC)
    name = export_filename(ExportKind.RESULTS, "Governor", at, ExportFormat.XLSX)
    assert name == "vtrs-results-Governor-20270312T093005Z-PROVISIONAL.xlsx"
    assert "PROVISIONAL" not in export_filename(ExportKind.AUDIT, "week", at, ExportFormat.CSV)


def test_each_kind_has_sensible_formats():
    assert ALLOWED_FORMATS[ExportKind.EVIDENCE_PACK] == (ExportFormat.ZIP,)
    assert ExportFormat.XLSX in ALLOWED_FORMATS[ExportKind.RESULTS]
    assert ExportFormat.XLSX not in ALLOWED_FORMATS[ExportKind.AUDIT]


def test_candidate_columns_follow_ballot_order():
    assert columns_for_candidates(["a", "b"], ["AAA", "B B"]) == [
        "a",
        "b",
        "votes_AAA",
        "votes_B-B",
    ]


def test_pack_paths_cannot_escape():
    path = evidence_path("../SYN 01/02", 2, "EC8A", "abc", "jpg")
    assert path == "evidence/SYN-01-02/v2-EC8A-abc.jpg"


def test_the_verifier_is_valid_standalone_python():
    compile(VERIFY_SCRIPT, "verify.py", "exec")
    assert "import hashlib" in VERIFY_SCRIPT and "django" not in VERIFY_SCRIPT.lower()
