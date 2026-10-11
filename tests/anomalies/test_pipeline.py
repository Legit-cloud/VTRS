"""Asynchronous rules running on real submissions and uploads (FR-6.9.x, AC-11)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.anomalies import analysis
from apps.anomalies.models import AnomalyFlag
from apps.core.domain.permissions import Role
from apps.core.rls import system_context
from apps.elections.models import Election
from apps.evidence.models import EvidenceFile
from apps.evidence.scanning import EICAR
from apps.evidence.storage import get_storage

from ..results.conftest import jpeg_bytes, manifest_entry
from .helpers import (
    flags_of,
    noise_photo,
    reencode,
    rules_of,
    submit_with_photo,
    unit_with_coordinates,
    version_state,
)

pytestmark = pytest.mark.django_db


def test_a_clean_submission_raises_nothing(field_):
    outcome = field_.submit(unit_with_coordinates(field_))
    assert flags_of(outcome["version_id"]) == []
    assert version_state(outcome["version_id"]) == "SUBMITTED"


def test_a_submission_from_far_away_is_flagged_and_sent_to_review(field_):
    pu = unit_with_coordinates(field_)
    far = {
        "lat": round(float(pu.latitude) + 0.5, 6),  # about 55 km
        "lng": float(pu.longitude),
        "accuracy_m": 10,
    }
    outcome = field_.submit(pu, gps=far)
    [flag] = flags_of(outcome["version_id"])
    assert flag.rule_code == "GPS_OUT_OF_GEOFENCE"
    assert flag.severity == "HIGH"
    assert flag.details["distance_m"] > 50_000
    assert version_state(outcome["version_id"]) == "REQUIRES_REVIEW"
    # The agent sees it on their next status poll, and the result still counts.
    status = (
        field_.agents[pu.id]
        .client.get("/api/v1/sync/status", {"ids": outcome["version_id"]})
        .json()[0]
    )
    assert status["status"] == "REQUIRES_REVIEW"
    dashboard = field_.admin_client().get(f"/api/v1/elections/{field_.election.id}/dashboard")
    assert dashboard.json()["contests"][0]["reported_pus"] == 1


def test_no_gps_at_all_is_a_medium_flag(field_):
    pu = field_.pus[0]
    outcome = field_.submit(pu, gps=None)
    assert rules_of(outcome["version_id"]) == {"GPS_MISSING"}


def test_a_poor_fix_is_information_only(field_):
    pu = unit_with_coordinates(field_)
    gps = {"lat": float(pu.latitude), "lng": float(pu.longitude), "accuracy_m": 450}
    outcome = field_.submit(pu, gps=gps)
    [flag] = flags_of(outcome["version_id"])
    assert (flag.rule_code, flag.severity) == ("GPS_LOW_ACCURACY", "INFO")
    assert version_state(outcome["version_id"]) == "SUBMITTED"  # INFO never forces a review


def test_a_result_captured_before_polls_closed_is_high(field_):
    with system_context():
        Election.objects.filter(id=field_.election.id).update(
            polls_open_at=timezone.now() - timedelta(days=1),
            polls_close_at=timezone.now() + timedelta(hours=2),
        )
    outcome = field_.submit(unit_with_coordinates(field_))
    [flag] = flags_of(outcome["version_id"])
    assert (flag.rule_code, flag.severity) == ("CAPTURED_BEFORE_POLLS_CLOSE", "HIGH")


def test_a_device_clock_in_the_future_is_flagged(field_):
    ahead = (timezone.now() + timedelta(hours=6)).isoformat()
    outcome = field_.submit(unit_with_coordinates(field_), device_captured_at=ahead)
    assert "DEVICE_CLOCK_AHEAD" in rules_of(outcome["version_id"])


def test_a_turnout_far_from_its_neighbours_is_flagged(big_field):
    f = big_field
    lga_units = [p for p in f.pus if p.lga_id == f.lgas[0].id]
    assert len(lga_units) >= 10
    for index, pu in enumerate(lga_units[:9]):
        votes = (150 + 4 * (index % 5), 140 + 3 * (index % 4))
        outcome = f.submit(
            pu,
            votes,
            gps={
                "lat": float(pu.latitude or 7.4),
                "lng": float(pu.longitude or 3.9),
                "accuracy_m": 8,
            },
        )
        assert "TURNOUT_OUTLIER" not in rules_of(outcome["version_id"])
    pu = lga_units[9]
    registered = pu.registered_voters
    cast = registered - 8  # about 98% turnout while the neighbours sit near 60%
    wild = f.submit(
        pu,
        (cast - 70, 70),
        totals={"accredited": registered, "valid": cast, "rejected": 0, "total_cast": cast},
        gps={"lat": float(pu.latitude or 7.4), "lng": float(pu.longitude or 3.9), "accuracy_m": 8},
    )
    flags = {fl.rule_code: fl for fl in flags_of(wild["version_id"])}
    assert flags["TURNOUT_OUTLIER"].severity == "HIGH"
    assert flags["TURNOUT_OUTLIER"].details["modified_z"] > 3.5


def test_a_photo_reused_at_another_unit_is_flagged(field_):
    f = field_
    photo = noise_photo(1)
    first = submit_with_photo(f, f.pus[0], photo)
    assert "DUPLICATE_EVIDENCE" not in rules_of(first["version_id"])  # nothing to match yet

    second = submit_with_photo(f, f.pus[1], photo)
    flag = next(x for x in flags_of(second["version_id"]) if x.rule_code == "DUPLICATE_EVIDENCE")
    assert flag.severity == "HIGH"
    assert str(f.pus[0].id) in flag.details["identical_at"]

    # A re-compressed copy of the same sheet is caught by the perceptual hash.
    third = submit_with_photo(f, f.pus[2], reencode(photo, 55))
    assert "DUPLICATE_EVIDENCE" in rules_of(third["version_id"])

    # A different photo is fine.
    fourth = submit_with_photo(f, f.pus[3], noise_photo(2))
    assert "DUPLICATE_EVIDENCE" not in rules_of(fourth["version_id"])


def test_a_corrected_submission_may_reuse_its_own_photo(field_):
    f = field_
    photo = noise_photo(5)
    first = submit_with_photo(f, f.pus[0], photo)
    again = submit_with_photo(f, f.pus[0], photo, parent_version_id=first["version_id"])
    assert "DUPLICATE_EVIDENCE" not in rules_of(again["version_id"])


def test_a_quarantined_photo_raises_a_flag(field_):
    f = field_
    pu = f.pus[0]
    bad = jpeg_bytes()[:-40] + EICAR  # a JPEG with the malware test signature appended
    entry = manifest_entry(bad)
    outcome = f.submit(pu, evidence=[entry])
    with system_context():
        key = EvidenceFile.objects.get(id=entry["evidence_id"]).object_key
    get_storage().write(key, bad, mime="image/jpeg")
    f.agents[pu.id].client.post(f"/api/v1/evidence/{entry['evidence_id']}/complete")
    [flag] = [x for x in flags_of(outcome["version_id"]) if x.rule_code == "EVIDENCE_QUARANTINED"]
    assert flag.severity == "HIGH"


def test_missing_evidence_is_swept_and_only_flagged_once(field_, settings):
    f = field_
    settings.VTRS_ANOMALY_THRESHOLDS = {"evidence_wait_minutes": 0}
    bare = f.submit(unit_with_coordinates(f))
    photographed = submit_with_photo(f, f.pus[3], noise_photo(9))

    assert analysis.check_missing_evidence() == 1
    assert "MISSING_EVIDENCE" in rules_of(bare["version_id"])
    assert "MISSING_EVIDENCE" not in rules_of(photographed["version_id"])
    assert analysis.check_missing_evidence() == 0  # idempotent


def test_analysis_is_idempotent(field_):
    f = field_
    pu = unit_with_coordinates(f)
    outcome = f.submit(
        pu,
        gps={
            "lat": round(float(pu.latitude) + 0.5, 6),
            "lng": float(pu.longitude),
            "accuracy_m": 10,
        },
    )
    before = flags_of(outcome["version_id"])
    again = analysis.analyze_version(f.org.id, outcome["version_id"])
    assert again == 0
    assert len(flags_of(outcome["version_id"])) == len(before)


def test_flags_never_remove_a_result_from_the_count(field_):
    f = field_
    pu = unit_with_coordinates(f)
    f.submit(
        pu,
        (70, 30),
        gps={
            "lat": round(float(pu.latitude) + 0.5, 6),
            "lng": float(pu.longitude),
            "accuracy_m": 10,
        },
    )
    top = f.admin_client().get(f"/api/v1/elections/{f.election.id}/dashboard").json()["contests"][0]
    assert {v["party_acronym"]: v["votes"] for v in top["votes"]} == {"AAA": 70, "BBB": 30}
    assert top["review_pus"] == 1
    assert top["open_flags"] >= 1


def test_officers_only_see_flags_in_their_geography(field_):
    f = field_
    pu_a, pu_b = unit_with_coordinates(f, 0), unit_with_coordinates(f, 2)
    for pu in (pu_a, pu_b):
        f.submit(
            pu,
            gps={
                "lat": round(float(pu.latitude) + 0.5, 6),
                "lng": float(pu.longitude),
                "accuracy_m": 9,
            },
        )
    url = f"/api/v1/elections/{f.election.id}/flags"
    assert len(f.admin_client().get(url).json()["results"]) == 2
    ward_a = f.officer_client(Role.WARD_OFFICER, f.wards[0]).get(url).json()["results"]
    assert [r["polling_unit_id"] for r in ward_a] == [str(pu_a.id)]
    lga_b = f.officer_client(Role.LGA_OFFICER, f.lgas[1]).get(url).json()["results"]
    assert [r["polling_unit_id"] for r in lga_b] == [str(pu_b.id)]
    assert f.agents[pu_a.id].client.get(url).status_code == 403
    with system_context():
        assert AnomalyFlag.objects.count() == 2
