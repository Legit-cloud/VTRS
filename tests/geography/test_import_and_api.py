import csv
import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.audit.models import AuditEvent
from apps.core.domain.permissions import Role
from apps.geography.domain.master_data import OPTIONAL_COLUMNS, REQUIRED_COLUMNS, Expectations
from apps.geography.domain.synthetic import synthetic_master_data
from apps.geography.models import Lga, PollingUnit, State, Ward
from apps.geography.services import import_master_data

pytestmark = pytest.mark.django_db

SMALL = {"lgas": 3, "wards": 6, "polling_units": 24}


@pytest.fixture
def small_geography():
    outcome = import_master_data(synthetic_master_data(**SMALL))
    assert outcome.applied
    return outcome


def test_import_creates_the_hierarchy_with_denormalized_ids(small_geography):
    assert small_geography.changes["polling_units"] == {"created": 24, "updated": 0}
    assert (State.objects.count(), Lga.objects.count(), Ward.objects.count()) == (1, 3, 6)
    for pu in PollingUnit.objects.select_related("ward"):
        assert pu.lga_id == pu.ward.lga_id
        assert pu.state_id == pu.ward.state_id


def test_reimport_is_idempotent_and_applies_changes(small_geography):
    rows = synthetic_master_data(**SMALL)
    again = import_master_data(rows)
    assert all(c == {"created": 0, "updated": 0} for c in again.changes.values())

    rows[0]["pu_name"] = "Renamed PU"
    changed = import_master_data(rows)
    assert changed.changes["polling_units"] == {"created": 0, "updated": 1}
    assert PollingUnit.objects.get(inec_code=rows[0]["pu_code"]).name == "Renamed PU"


def test_import_is_audited(small_geography):
    event = AuditEvent.objects.get(action="geography.master_data_imported")
    assert event.diff["counts"]["polling_units"] == 24
    assert event.actor_id is None  # run by an operator command, not a user


def test_invalid_dataset_writes_nothing():
    rows = synthetic_master_data(**SMALL)
    rows[5]["pu_code"] = rows[4]["pu_code"]
    outcome = import_master_data(rows)
    assert not outcome.applied
    assert PollingUnit.objects.count() == 0
    assert not AuditEvent.objects.exists()


def test_removed_polling_units_are_reported_not_deleted(small_geography):
    rows = synthetic_master_data(**SMALL)[:-1]
    outcome = import_master_data(rows)
    assert PollingUnit.objects.count() == 24
    assert "1 polling units in the database are not in this file" in outcome.report.warnings


@pytest.mark.slow
def test_full_oyo_shaped_import_passes_the_m0_gate():
    oyo = Expectations(lgas=33, wards=351, polling_units=6390, polling_unit_tolerance=0.02)
    outcome = import_master_data(synthetic_master_data(), expectations=oyo)
    assert outcome.applied, outcome.report.errors
    assert (Lga.objects.count(), Ward.objects.count(), PollingUnit.objects.count()) == (
        33,
        351,
        6390,
    )


def _write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED_COLUMNS + OPTIONAL_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def test_import_command_dry_run_and_report(tmp_path):
    source, report = tmp_path / "pu.csv", tmp_path / "report.json"
    _write_csv(source, synthetic_master_data(**SMALL))
    call_command("import_master_data", source, "--no-expectations", "--dry-run", "--report", report)
    assert PollingUnit.objects.count() == 0
    assert json.loads(report.read_text())["counts"]["polling_units"] == 24

    call_command("import_master_data", source, "--no-expectations")
    assert PollingUnit.objects.count() == 24


def test_import_command_enforces_expected_counts(tmp_path):
    source = tmp_path / "pu.csv"
    _write_csv(source, synthetic_master_data(**SMALL))
    with pytest.raises(CommandError, match="Import rejected"):
        call_command("import_master_data", source)


def test_generate_synthetic_command(tmp_path):
    out = tmp_path / "synthetic.csv"
    call_command("generate_synthetic_geography", "--out", out)
    with out.open(encoding="utf-8") as handle:
        assert sum(1 for _ in csv.DictReader(handle)) == 6390


# --- API ------------------------------------------------------------------------------------


@pytest.mark.parametrize("role", list(Role))
def test_every_role_can_read_master_data(small_geography, client_as, make_actor, role):
    response = client_as(make_actor(role)).get("/api/v1/geography/lgas")
    assert response.status_code == 200
    assert [r["inec_code"] for r in response.json()["results"]] == ["SYN-01", "SYN-02", "SYN-03"]


def test_filters_and_keyset_pagination(small_geography, client_as, make_actor):
    client = client_as(make_actor())
    lga = Lga.objects.get(inec_code="SYN-01")
    wards = client.get("/api/v1/geography/wards", {"lga": lga.id}).json()["results"]
    assert {w["lga_id"] for w in wards} == {str(lga.id)}

    page = client.get("/api/v1/geography/polling-units", {"lga": lga.id, "limit": 3}).json()
    assert len(page["results"]) == 3
    assert "cursor=" in page["next"]
    assert "previous" in page and "count" not in page  # keyset, no offsets or totals


def test_unknown_and_malformed_query_params(small_geography, client_as, make_actor):
    client = client_as(make_actor())
    response = client.get("/api/v1/geography/wards", {"lga_id": "x"})
    assert response.status_code == 400
    assert response.json()["code"] == "unknown_query_parameter"

    response = client.get("/api/v1/geography/wards", {"lga": "not-a-uuid"})
    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"
    assert response.json()["errors"] == {"lga": ["Must be a UUID."]}


def test_master_data_is_read_only_over_the_api(small_geography, client_as, make_actor):
    response = client_as(make_actor()).post("/api/v1/geography/lgas", {}, format="json")
    assert response.status_code == 405
    assert response.json()["code"] == "method_not_allowed"
