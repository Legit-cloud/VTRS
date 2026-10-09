"""FR-6.4.1 - FR-6.4.4: master-data validation (pure, no database)."""

from apps.geography.domain.master_data import Expectations, parse_and_validate
from apps.geography.domain.synthetic import synthetic_master_data

OYO = Expectations(lgas=33, wards=351, polling_units=6390, polling_unit_tolerance=0.02)


def test_synthetic_dataset_has_the_oyo_shape():
    report = parse_and_validate(synthetic_master_data(), OYO)
    assert report.ok, report.errors
    assert report.counts == {"states": 1, "lgas": 33, "wards": 351, "polling_units": 6390}
    assert 0.9 < report.coordinate_coverage < 1.0
    assert any("no coordinates" in w for w in report.warnings)


def test_count_mismatch_is_an_error():
    report = parse_and_validate(synthetic_master_data(lgas=32, wards=351), OYO)
    assert not report.ok
    assert "expected 33 LGAs, found 32" in report.errors


def test_polling_unit_count_tolerance():
    near = synthetic_master_data(polling_units=6300)  # within 2%
    far = synthetic_master_data(polling_units=6000)
    assert parse_and_validate(near, OYO).ok
    assert not parse_and_validate(far, OYO).ok


def _rows(n=4):
    return synthetic_master_data(lgas=1, wards=2, polling_units=n, missing_coordinate_ratio=0)


def test_duplicate_polling_unit_codes():
    rows = _rows()
    rows[3]["pu_code"] = rows[0]["pu_code"]
    report = parse_and_validate(rows)
    assert report.error_count == 1
    assert "duplicates line 2" in report.errors[0]


def test_ward_with_two_parents():
    rows = _rows()
    rows[1]["lga_code"] = "SYN-99"
    report = parse_and_validate(rows)
    assert not report.ok
    assert any("ward SYN-01-01 conflicts" in e for e in report.errors)


def test_field_level_errors():
    rows = _rows(6)
    rows[0]["pu_name"] = " "
    rows[1]["latitude"] = ""
    rows[2]["latitude"], rows[2]["longitude"] = "51.5", "-0.12"  # London
    rows[3]["registered_voters"] = "-5"
    rows[4]["longitude"] = "east"
    report = parse_and_validate(rows)
    assert report.error_count == 5
    joined = "\n".join(report.errors)
    assert "line 2: missing pu_name" in joined
    assert "line 3: latitude and longitude must both be present" in joined
    assert "line 4: coordinates 51.500000,-0.120000 are outside Nigeria" in joined
    assert "line 5: registered_voters" in joined
    assert "line 6: coordinates are not numbers" in joined


def test_empty_dataset():
    report = parse_and_validate([])
    assert report.errors == ["the dataset has no rows"]


def test_error_list_is_capped_but_counted():
    rows = _rows(300)
    for row in rows:
        row["pu_name"] = ""
    report = parse_and_validate(rows)
    assert report.error_count == 300
    assert len(report.errors) == 200
