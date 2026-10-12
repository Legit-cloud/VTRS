"""Contextual, statistical and evidence rules (FR-6.9.2 - FR-6.9.5).

Pure functions over plain values. Every threshold is a field of `Thresholds`, filled from
settings, so the escalation team can tune a rule without touching code. Defaults follow common
election-monitoring practice:

* Geofence 300 m around the polling unit, widened by the fix's own reported accuracy, with
  "far" (HIGH) beyond 2 km. Consumer GPS is good to 5-50 m outdoors, so 300 m separates "in the
  school compound" from "somewhere else" without drowning reviewers in noise.
* Outliers use the modified z-score (Iglewicz and Hoaglin): 0.6745 * (x - median) / MAD with a
  cut-off of 3.5. It is robust to the very outliers it hunts, unlike a mean and standard
  deviation, and needs a minimum number of comparable polling units.
* A photo reused at another polling unit is found with a 64-bit difference hash and a Hamming
  distance of 4 or less (re-photographed or re-compressed copies of one sheet).

A finding never removes a result from the count: it routes it to a human.
"""

import math
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from .inline import Finding, RuleCode, Severity

EARTH_RADIUS_M = 6_371_000.0
# Scales MAD to a standard deviation for normally distributed data.
MAD_SCALE = 0.6745
# Scales the mean absolute deviation, used when more than half the peers are identical.
MEAN_AD_SCALE = 1.253314


@dataclass(frozen=True, slots=True)
class Thresholds:
    geofence_m: float = 300.0
    far_m: float = 2000.0
    max_accuracy_m: float = 100.0
    future_skew_seconds: int = 300
    outlier_z: float = 3.5
    min_peers: int = 8
    implausible_turnout: float = 0.90
    rejected_rate_max: float = 0.10
    rejected_min_cast: int = 30
    unanimous_min_votes: int = 50
    evidence_wait_minutes: int = 30
    exif_time_tolerance_hours: float = 3.0
    dhash_distance: int = 4


def distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance (haversine) in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    d_phi = p2 - p1
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def _geofence(
    where: Mapping[str, float],
    pu: tuple[float | None, float | None],
    accuracy: float | None,
    t: Thresholds,
    rule: RuleCode,
) -> Finding | None:
    if pu[0] is None or pu[1] is None:
        return None  # no reference point for this polling unit, so nothing to compare
    metres = distance_m(where["lat"], where["lng"], pu[0], pu[1])
    slack = accuracy or 0.0
    if metres - slack <= t.geofence_m:
        return None
    return Finding(
        rule,
        {
            "distance_m": round(metres),
            "accuracy_m": accuracy,
            "geofence_m": t.geofence_m,
        },
        severity_override=Severity.HIGH if metres - slack > t.far_m else None,
    )


def gps_findings(
    *,
    lat: float | None,
    lng: float | None,
    accuracy_m: float | None,
    pu_lat: float | None,
    pu_lng: float | None,
    t: Thresholds,
) -> list[Finding]:
    if lat is None or lng is None:
        return [Finding(RuleCode.GPS_MISSING, {})]
    findings: list[Finding] = []
    outside = _geofence(
        {"lat": lat, "lng": lng}, (pu_lat, pu_lng), accuracy_m, t, RuleCode.GPS_OUT_OF_GEOFENCE
    )
    if outside:
        findings.append(outside)
    if accuracy_m is not None and accuracy_m > t.max_accuracy_m:
        findings.append(
            Finding(
                RuleCode.GPS_LOW_ACCURACY,
                {"accuracy_m": accuracy_m, "max_accuracy_m": t.max_accuracy_m},
            )
        )
    return findings


def timing_findings(
    *,
    captured_at: datetime,
    received_at: datetime,
    polls_open_at: datetime | None,
    polls_close_at: datetime | None,
    t: Thresholds,
) -> list[Finding]:
    """Device time is untrusted, but impossible values are themselves a signal."""
    findings: list[Finding] = []
    if captured_at > received_at + timedelta(seconds=t.future_skew_seconds):
        findings.append(
            Finding(
                RuleCode.DEVICE_CLOCK_AHEAD,
                {
                    "captured_at": captured_at.isoformat(),
                    "received_at": received_at.isoformat(),
                },
            )
        )
    if polls_open_at is not None and captured_at < polls_open_at:
        findings.append(
            Finding(
                RuleCode.CAPTURED_BEFORE_POLLS_OPEN,
                {
                    "captured_at": captured_at.isoformat(),
                    "polls_open_at": polls_open_at.isoformat(),
                },
            )
        )
    elif polls_close_at is not None and captured_at < polls_close_at:
        # A result sheet cannot exist before voting ends and counting is done.
        findings.append(
            Finding(
                RuleCode.CAPTURED_BEFORE_POLLS_CLOSE,
                {
                    "captured_at": captured_at.isoformat(),
                    "polls_close_at": polls_close_at.isoformat(),
                },
            )
        )
    return findings


# --- Statistical ------------------------------------------------------------------------------


def modified_z(value: float, peers: Sequence[float]) -> float | None:
    """Iglewicz-Hoaglin modified z-score of `value` against `peers`.

    Returns None when the peers have no spread at all (nothing to measure against)."""
    if not peers:
        return None
    median = statistics.median(peers)
    mad = statistics.median(abs(p - median) for p in peers)
    if mad > 0:
        return MAD_SCALE * (value - median) / mad
    mean_ad = statistics.fmean(abs(p - median) for p in peers)
    if mean_ad > 0:
        return (value - median) / (MEAN_AD_SCALE * mean_ad)
    return None


@dataclass(frozen=True, slots=True)
class Figures:
    """What the statistical rules need to know about one polling unit's counting result."""

    valid: int
    rejected: int | None
    total_cast: int | None
    accredited: int | None
    registered: int | None
    top_votes: int  # votes of the leading candidate

    @property
    def turnout(self) -> float | None:
        cast = self.total_cast if self.total_cast is not None else self.valid
        base = self.registered or self.accredited
        return cast / base if base else None

    @property
    def top_share(self) -> float | None:
        return self.top_votes / self.valid if self.valid else None


def statistical_findings(
    figures: Figures, peers: Iterable[Figures], t: Thresholds
) -> list[Finding]:
    findings: list[Finding] = []
    peer_list = list(peers)

    if figures.rejected is not None and figures.total_cast:
        rate = figures.rejected / figures.total_cast
        if figures.total_cast >= t.rejected_min_cast and rate > t.rejected_rate_max:
            findings.append(
                Finding(
                    RuleCode.HIGH_REJECTED_RATE,
                    {
                        "rejected": figures.rejected,
                        "total_cast": figures.total_cast,
                        "rate": round(rate, 3),
                        "max_rate": t.rejected_rate_max,
                    },
                )
            )
    if figures.valid >= t.unanimous_min_votes and figures.top_votes == figures.valid:
        findings.append(Finding(RuleCode.UNANIMOUS_RESULT, {"valid": figures.valid}))

    turnout = figures.turnout
    peer_turnouts = [p.turnout for p in peer_list if p.turnout is not None]
    if turnout is not None and len(peer_turnouts) >= t.min_peers:
        z = modified_z(turnout, peer_turnouts)
        if z is not None and abs(z) > t.outlier_z:
            findings.append(
                Finding(
                    RuleCode.TURNOUT_OUTLIER,
                    {
                        "turnout": round(turnout, 3),
                        "peer_median": round(statistics.median(peer_turnouts), 3),
                        "modified_z": round(z, 2),
                        "peers": len(peer_turnouts),
                    },
                    severity_override=(
                        Severity.HIGH if turnout >= t.implausible_turnout and z > 0 else None
                    ),
                )
            )
    share = figures.top_share
    peer_shares = [p.top_share for p in peer_list if p.top_share is not None]
    if share is not None and len(peer_shares) >= t.min_peers:
        z = modified_z(share, peer_shares)
        if z is not None and abs(z) > t.outlier_z:
            findings.append(
                Finding(
                    RuleCode.VOTE_SHARE_OUTLIER,
                    {
                        "top_share": round(share, 3),
                        "peer_median": round(statistics.median(peer_shares), 3),
                        "modified_z": round(z, 2),
                        "peers": len(peer_shares),
                    },
                )
            )
    return findings


# --- Evidence -----------------------------------------------------------------------------------


def hamming(a_hex: str, b_hex: str) -> int:
    return (int(a_hex, 16) ^ int(b_hex, 16)).bit_count()


def duplicate_evidence(
    *,
    dhash: str | None,
    sha256: str,
    others: Iterable[tuple[UUID, str | None, str]],
    t: Thresholds,
) -> list[Finding]:
    """`others` are (polling_unit_id, dhash, sha256) of verified photos at *other* units."""
    exact: set[UUID] = set()
    near: dict[UUID, int] = {}
    for unit_id, other_hash, other_sha in others:
        if other_sha and other_sha == sha256:
            exact.add(unit_id)
        elif dhash and other_hash and hamming(dhash, other_hash) <= t.dhash_distance:
            near[unit_id] = min(near.get(unit_id, 64), hamming(dhash, other_hash))
    if not exact and not near:
        return []
    return [
        Finding(
            RuleCode.DUPLICATE_EVIDENCE,
            {
                "identical_at": sorted(str(u) for u in exact),
                "similar_at": {
                    str(u): d for u, d in sorted(near.items(), key=lambda kv: str(kv[0]))
                },
                "max_distance": t.dhash_distance,
            },
        )
    ]


def exif_findings(
    *,
    exif_taken_at: datetime | None,
    device_captured_at: datetime,
    exif_gps: Mapping[str, float] | None,
    pu_lat: float | None,
    pu_lng: float | None,
    t: Thresholds,
) -> list[Finding]:
    """Compare the photo's own metadata with what the app declared. Missing metadata is not a
    finding: many cameras and re-encoders strip it."""
    findings: list[Finding] = []
    if exif_taken_at is not None:
        # EXIF carries the camera's wall-clock time without a zone; the device's declared
        # capture time carries its own offset, so compare wall clocks.
        declared_wall = device_captured_at.replace(tzinfo=None)
        gap = abs((exif_taken_at - declared_wall).total_seconds()) / 3600
        if gap > t.exif_time_tolerance_hours:
            findings.append(
                Finding(
                    RuleCode.EXIF_TIME_MISMATCH,
                    {
                        "exif_taken_at": exif_taken_at.isoformat(),
                        "declared_at": declared_wall.isoformat(),
                        "gap_hours": round(gap, 1),
                    },
                )
            )
    if exif_gps and pu_lat is not None and pu_lng is not None:
        metres = distance_m(exif_gps["lat"], exif_gps["lng"], pu_lat, pu_lng)
        if metres > t.far_m:
            findings.append(
                Finding(
                    RuleCode.EXIF_GPS_MISMATCH,
                    {"distance_m": round(metres), "limit_m": t.far_m},
                )
            )
    return findings


def evidence_details(status: str, reason: str) -> dict[str, Any]:
    return {"status": status, "reason": reason}
