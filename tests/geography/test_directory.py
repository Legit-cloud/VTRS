"""Names-only directory conversion (pure, no database)."""

from pathlib import Path

import pytest

from apps.geography.domain.directory import DirectoryFormatError, parse_directory
from apps.geography.domain.master_data import Expectations, parse_and_validate

SAMPLE = """\
# Oyo State: Polling Unit Directory

## Afijio LGA


### Awe I Ward (2 PUs)

1. Alagbede Open Space
2. Asaalu Open Space

### Awe II Ward (1 PUs)

1. Awe High School Awe

## Akinyele LGA


### Iroko Ward (2 PUs)

1. Olowogbo Village
2. Olowogbo Village
"""


def _rows(text: str):
    return list(parse_directory(text.splitlines(), state_code="OY", state_name="Oyo"))


def test_rows_carry_provisional_positional_codes():
    rows = _rows(SAMPLE)
    assert [r["pu_code"] for r in rows] == [
        "DIR-OY-01-001-001",
        "DIR-OY-01-001-002",
        "DIR-OY-01-002-001",
        "DIR-OY-02-001-001",
        "DIR-OY-02-001-002",
    ]
    first = rows[0]
    assert first["state_code"] == "DIR-OY"
    assert first["lga_name"] == "Afijio"
    assert first["ward_name"] == "Awe I"
    assert first["latitude"] == first["longitude"] == first["registered_voters"] == ""


def test_same_name_twice_in_a_ward_stays_two_units():
    rows = _rows(SAMPLE)
    assert [r["pu_name"] for r in rows[-2:]] == ["Olowogbo Village", "Olowogbo Village"]
    assert len({r["pu_code"] for r in rows}) == len(rows)


def test_rows_pass_master_data_validation():
    report = parse_and_validate(_rows(SAMPLE))
    assert report.ok, report.errors
    assert report.counts == {"states": 1, "lgas": 2, "wards": 3, "polling_units": 5}


def test_declared_count_must_match_listed_units():
    broken = SAMPLE.replace("Awe I Ward (2 PUs)", "Awe I Ward (3 PUs)")
    with pytest.raises(DirectoryFormatError, match="declares 3 polling units but lists 2"):
        _rows(broken)


def test_unit_outside_a_ward_is_rejected():
    with pytest.raises(DirectoryFormatError, match="line 3: polling unit is outside a ward"):
        _rows("## Afijio LGA\n\n1. Stray Unit\n")


def test_ward_outside_an_lga_is_rejected():
    with pytest.raises(DirectoryFormatError, match="outside an LGA"):
        _rows("### Awe I Ward (1 PUs)\n\n1. Alagbede\n")


@pytest.mark.parametrize(
    ("slug", "code", "name", "lgas", "wards", "units"),
    [
        ("oyo", "OY", "Oyo", 33, 351, 4731),
        ("ogun", "OG", "Ogun", 20, 236, 3184),
        ("ekiti", "EK", "Ekiti", 16, 177, 2191),
    ],
)
def test_bundled_directories_have_their_published_totals(slug, code, name, lgas, wards, units):
    path = Path(__file__).resolve().parents[2] / "data" / "master" / f"{slug}-directory.md"
    with path.open(encoding="utf-8") as handle:
        rows = list(parse_directory(handle, state_code=code, state_name=name))
    report = parse_and_validate(rows, Expectations(lgas=lgas, wards=wards, polling_units=units))
    assert report.ok, report.errors
    assert report.counts == {"states": 1, "lgas": lgas, "wards": wards, "polling_units": units}


def test_state_codes_do_not_collide_across_states():
    root = Path(__file__).resolve().parents[2] / "data" / "master"
    seen: set[str] = set()
    for slug, code, name in (
        ("oyo", "OY", "Oyo"),
        ("ogun", "OG", "Ogun"),
        ("ekiti", "EK", "Ekiti"),
    ):
        with (root / f"{slug}-directory.md").open(encoding="utf-8") as handle:
            codes = {
                r["pu_code"] for r in parse_directory(handle, state_code=code, state_name=name)
            }
        assert not codes & seen
        seen |= codes
