"""The anomaly rules as pure arithmetic (FR-6.9.2 - FR-6.9.5)."""

from datetime import UTC, datetime, timedelta

import pytest

from apps.anomalies.domain.contextual import (
    Figures,
    Thresholds,
    distance_m,
    duplicate_evidence,
    exif_findings,
    gps_findings,
    hamming,
    modified_z,
    statistical_findings,
    timing_findings,
)
from apps.anomalies.domain.escalation import (
    DEFAULT_MATRIX,
    Channel,
    Level,
    initial_due,
    is_overdue,
    matrix_from_settings,
    next_level,
    top_level,
)
from apps.anomalies.domain.inline import RuleCode, Severity
from apps.core.ids import uuid7

T = Thresholds()
PU = (7.40, 3.90)


def _rules(findings):
    return [f.rule for f in findings]


# --- GPS ------------------------------------------------------------------------------------


def test_distance_is_roughly_right():
    # One degree of latitude is about 111 km.
    assert distance_m(7.0, 3.0, 8.0, 3.0) == pytest.approx(111_195, rel=0.001)
    assert distance_m(7.4, 3.9, 7.4, 3.9) == 0


def test_a_fix_inside_the_compound_is_fine():
    found = gps_findings(lat=7.4005, lng=3.9, accuracy_m=10, pu_lat=PU[0], pu_lng=PU[1], t=T)
    assert found == []


def test_a_fix_far_from_the_unit_is_flagged_and_far_is_high():
    near = gps_findings(lat=7.41, lng=3.9, accuracy_m=10, pu_lat=PU[0], pu_lng=PU[1], t=T)
    assert _rules(near) == [RuleCode.GPS_OUT_OF_GEOFENCE]
    assert near[0].severity is Severity.MEDIUM  # about 1.1 km
    far = gps_findings(lat=7.5, lng=3.9, accuracy_m=10, pu_lat=PU[0], pu_lng=PU[1], t=T)
    assert far[0].severity is Severity.HIGH  # about 11 km


def test_reported_accuracy_widens_the_geofence():
    # 356 m away is outside 300 m, but not if the fix itself says "within 90 m".
    lat = PU[0] + 0.0032
    assert gps_findings(lat=lat, lng=PU[1], accuracy_m=5, pu_lat=PU[0], pu_lng=PU[1], t=T)
    assert not gps_findings(lat=lat, lng=PU[1], accuracy_m=90, pu_lat=PU[0], pu_lng=PU[1], t=T)


def test_missing_and_imprecise_gps():
    missing = gps_findings(lat=None, lng=None, accuracy_m=None, pu_lat=PU[0], pu_lng=PU[1], t=T)
    assert _rules(missing) == [RuleCode.GPS_MISSING]
    imprecise = gps_findings(lat=PU[0], lng=PU[1], accuracy_m=500, pu_lat=PU[0], pu_lng=PU[1], t=T)
    assert _rules(imprecise) == [RuleCode.GPS_LOW_ACCURACY]
    assert imprecise[0].severity is Severity.INFO


def test_a_unit_without_coordinates_cannot_be_compared():
    assert gps_findings(lat=1.0, lng=1.0, accuracy_m=5, pu_lat=None, pu_lng=None, t=T) == []


# --- Timing -----------------------------------------------------------------------------------

NOW = datetime(2027, 3, 11, 18, 0, tzinfo=UTC)


def test_timing_rules():
    opened, closed = NOW - timedelta(hours=10), NOW - timedelta(hours=3)
    ok = timing_findings(
        captured_at=NOW - timedelta(minutes=30),
        received_at=NOW,
        polls_open_at=opened,
        polls_close_at=closed,
        t=T,
    )
    assert ok == []
    early = timing_findings(
        captured_at=opened - timedelta(hours=1),
        received_at=NOW,
        polls_open_at=opened,
        polls_close_at=closed,
        t=T,
    )
    assert _rules(early) == [RuleCode.CAPTURED_BEFORE_POLLS_OPEN]
    before_close = timing_findings(
        captured_at=closed - timedelta(hours=1),
        received_at=NOW,
        polls_open_at=opened,
        polls_close_at=closed,
        t=T,
    )
    assert _rules(before_close) == [RuleCode.CAPTURED_BEFORE_POLLS_CLOSE]
    ahead = timing_findings(
        captured_at=NOW + timedelta(hours=2),
        received_at=NOW,
        polls_open_at=None,
        polls_close_at=None,
        t=T,
    )
    assert _rules(ahead) == [RuleCode.DEVICE_CLOCK_AHEAD]


def test_small_clock_skew_is_tolerated():
    skew = timing_findings(
        captured_at=NOW + timedelta(seconds=120),
        received_at=NOW,
        polls_open_at=None,
        polls_close_at=None,
        t=T,
    )
    assert skew == []


# --- Statistics -------------------------------------------------------------------------------


def _figures(cast, registered=500, valid=None, top=None, rejected=5):
    valid = valid if valid is not None else cast - rejected
    return Figures(valid, rejected, cast, cast + 5, registered, top or valid // 2)


def test_modified_z_flags_the_outlier_and_not_the_crowd():
    peers = [0.58, 0.60, 0.61, 0.62, 0.59, 0.63, 0.60, 0.64]
    assert abs(modified_z(0.62, peers)) < 1
    assert modified_z(0.98, peers) > 3.5


def test_modified_z_with_no_spread_is_undefined():
    assert modified_z(0.9, [0.6] * 8) is None
    assert modified_z(0.9, []) is None


def test_a_turnout_outlier_is_found_and_implausible_turnout_is_high():
    peers = [_figures(c) for c in (290, 300, 310, 305, 295, 315, 300, 298, 302, 308)]
    normal = statistical_findings(_figures(306), peers, T)
    assert RuleCode.TURNOUT_OUTLIER not in _rules(normal)
    wild = statistical_findings(_figures(490), peers, T)
    outlier = next(f for f in wild if f.rule is RuleCode.TURNOUT_OUTLIER)
    assert outlier.severity is Severity.HIGH
    assert outlier.details["modified_z"] > 3.5


def test_too_few_peers_means_no_statistical_judgement():
    peers = [_figures(c) for c in (300, 310, 305)]
    assert RuleCode.TURNOUT_OUTLIER not in _rules(statistical_findings(_figures(490), peers, T))


def test_rejected_rate_and_unanimity_do_not_need_peers():
    many_rejected = Figures(
        valid=200, rejected=60, total_cast=260, accredited=270, registered=500, top_votes=100
    )
    assert _rules(statistical_findings(many_rejected, [], T)) == [RuleCode.HIGH_REJECTED_RATE]
    unanimous = Figures(
        valid=180, rejected=2, total_cast=182, accredited=190, registered=500, top_votes=180
    )
    assert _rules(statistical_findings(unanimous, [], T)) == [RuleCode.UNANIMOUS_RESULT]
    small = Figures(
        valid=20, rejected=0, total_cast=20, accredited=20, registered=500, top_votes=20
    )
    assert statistical_findings(small, [], T) == []  # too few votes to call it unanimous


def test_vote_share_outlier():
    peers = [
        Figures(200, 5, 205, 210, 500, top) for top in (110, 115, 120, 118, 112, 121, 117, 114)
    ]
    skewed = Figures(200, 5, 205, 210, 500, 199)
    assert RuleCode.VOTE_SHARE_OUTLIER in _rules(statistical_findings(skewed, peers, T))


# --- Evidence ---------------------------------------------------------------------------------


def test_hamming():
    assert hamming("ff", "ff") == 0
    assert hamming("ff", "fe") == 1
    assert hamming("0" * 16, "f" * 16) == 64


def test_duplicate_photo_at_another_unit():
    other, third = uuid7(), uuid7()
    found = duplicate_evidence(
        dhash="aaaaaaaaaaaaaaaa",
        sha256="s1",
        others=[
            (other, "aaaaaaaaaaaaaaab", "s2"),  # one bit away
            (third, "5555555555555555", "s3"),  # unrelated
        ],
        t=T,
    )
    assert _rules(found) == [RuleCode.DUPLICATE_EVIDENCE]
    assert found[0].details["similar_at"] == {str(other): 1}
    exact = duplicate_evidence(dhash=None, sha256="s1", others=[(other, None, "s1")], t=T)
    assert exact[0].details["identical_at"] == [str(other)]
    assert duplicate_evidence(dhash="a" * 16, sha256="s", others=[], t=T) == []


def test_exif_checks_compare_declared_and_embedded_values():
    declared = datetime(2027, 3, 11, 15, 40, tzinfo=UTC)
    ok = exif_findings(
        exif_taken_at=datetime(2027, 3, 11, 15, 10),
        device_captured_at=declared,
        exif_gps={"lat": PU[0], "lng": PU[1]},
        pu_lat=PU[0],
        pu_lng=PU[1],
        t=T,
    )
    assert ok == []
    bad = exif_findings(
        exif_taken_at=datetime(2027, 3, 9, 8, 0),
        device_captured_at=declared,
        exif_gps={"lat": 9.0, "lng": 3.9},
        pu_lat=PU[0],
        pu_lng=PU[1],
        t=T,
    )
    assert set(_rules(bad)) == {RuleCode.EXIF_TIME_MISMATCH, RuleCode.EXIF_GPS_MISMATCH}
    # Stripped metadata is not a finding.
    assert (
        exif_findings(
            exif_taken_at=None,
            device_captured_at=declared,
            exif_gps=None,
            pu_lat=PU[0],
            pu_lng=PU[1],
            t=T,
        )
        == []
    )


# --- Escalation matrix -------------------------------------------------------------------------


def test_the_default_matrix_is_ordered_by_severity():
    crit, high, med, info = (
        DEFAULT_MATRIX[s]
        for s in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.INFO)
    )
    assert top_level(crit) is Level.ADMIN
    assert top_level(high) is Level.LGA
    assert top_level(med) is Level.WARD
    assert crit.ack_minutes < high.ack_minutes < med.ack_minutes
    assert info.notify == () and info.ack_minutes is None
    assert Channel.SMS in crit.channels


def test_the_chain_of_command():
    assert next_level(Level.WARD) is Level.LGA
    assert next_level(Level.LGA) is Level.ADMIN
    assert next_level(Level.ADMIN) is None
    due = initial_due(DEFAULT_MATRIX[Severity.CRITICAL], NOW)
    assert due == NOW + timedelta(minutes=15)
    assert is_overdue(due, NOW + timedelta(minutes=16))
    assert not is_overdue(due, NOW + timedelta(minutes=14))
    assert initial_due(DEFAULT_MATRIX[Severity.INFO], NOW) is None


def test_the_matrix_can_be_tuned_from_settings():
    tuned = matrix_from_settings(
        {"HIGH": {"notify": ["WARD", "LGA", "ADMIN"], "ack_minutes": 10, "channels": ["IN_APP"]}}
    )
    assert top_level(tuned[Severity.HIGH]) is Level.ADMIN
    assert tuned[Severity.HIGH].ack_minutes == 10
    assert tuned[Severity.HIGH].channels == (Channel.IN_APP,)
    assert tuned[Severity.CRITICAL] == DEFAULT_MATRIX[Severity.CRITICAL]  # untouched
