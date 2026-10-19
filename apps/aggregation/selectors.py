"""War room reads (FR-6.8.1 - FR-6.8.8). Every read is narrowed to the actor's geography.

Rollups are stored per contest (one constituency's race). The war room works per election: an
area's figures are the sum of the contest rollups for that area, and contestants' votes are
grouped by party id (a governorship has one contest; a senatorial election in a state has one
per district). Within a single constituency each party's row also names its contestant.

A scoped coordinator's top level is their own area: LGA coordinators start at their LGAs, ward
coordinators at their wards. The state total is not shown to them, because it includes areas
they may not see (spec section 8). Figures are provisional and carry `PROVISIONAL_NOTICE`.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db.models import Count, Q, QuerySet
from django.db.models.functions import TruncHour, TruncMinute
from rest_framework.exceptions import NotFound, ValidationError

from apps.anomalies.models import AnomalyFlag
from apps.core.authz import authorize
from apps.core.domain.actor import Actor, ScopeKind
from apps.core.domain.permissions import Perm
from apps.elections import selectors as elections
from apps.elections.models import Candidate, Election
from apps.geography.models import Lga, PollingUnit, State, Ward
from apps.results.domain.versions import REPORTED_STATES, VERIFIED_STATES, completion_of
from apps.results.models import PuResult, ResultVersion, VoteLine

from .domain.tally import (
    PROVISIONAL_NOTICE,
    Measure,
    PartyInfo,
    RollupLevel,
    coverage_pct,
    merge_votes,
    position,
)
from .models import Rollup

_SCOPE_TOP_LEVEL = {
    ScopeKind.ORG: RollupLevel.STATE,
    ScopeKind.LGA: RollupLevel.LGA,
    ScopeKind.WARD: RollupLevel.WARD,
}
_SHEET = ("accredited", "valid", "rejected", "total_cast")
_COUNTS = ("expected_pus", "reported_pus", "verified_pus", "review_pus", "open_flags")
_ORDER = [RollupLevel.STATE, RollupLevel.LGA, RollupLevel.WARD, RollupLevel.PU]


def default_measure(election: Election) -> Measure:
    return Measure(election.count_policy)


def parse_measure(raw: str | None, election: Election) -> Measure:
    if raw is None:
        return default_measure(election)
    try:
        return Measure(raw.upper())
    except ValueError:
        raise ValidationError({"measure": ["Use reported or verified."]}) from None


def _narrow_pct() -> float:
    return float(getattr(settings, "VTRS_NARROW_MARGIN_PCT", 5.0))


@dataclass(frozen=True)
class _Ballot:
    """An election's contesting parties and every contestant, by id."""

    parties: list[PartyInfo]
    party_views: list[dict[str, Any]]
    # contestant id -> (party id, contest id, contestant name)
    contestants: dict[UUID, tuple[UUID, UUID, str]]


def _ballot(actor: Actor, election: Election) -> _Ballot:
    entries = list(elections.election_parties(actor, election))
    parties = [
        PartyInfo(e.party_id, e.party.abbreviation, e.ballot_order, e.party.is_own) for e in entries
    ]
    views = [
        {
            "party_id": e.party_id,
            "abbreviation": e.party.abbreviation,
            "full_name": e.party.full_name,
            "ballot_order": e.ballot_order,
            "is_own": e.party.is_own,
            "logo_url": elections.logo_url(e.party),
        }
        for e in entries
    ]
    contestants = {
        c.id: (c.party_id, c.contest_id, c.name)
        for c in Candidate.objects.in_organization(actor).filter(contest__election=election)
    }
    return _Ballot(parties, views, contestants)


def _area_names(level: str, ids: Iterable[UUID]) -> dict[UUID, dict[str, str]]:
    models: dict[str, type[State | Lga | Ward]] = {"STATE": State, "LGA": Lga, "WARD": Ward}
    model = models[level]
    return {
        obj.id: {"name": obj.name, "code": obj.inec_code}
        for obj in model.objects.filter(id__in=list(ids))
    }


def _compose(
    *,
    level: str,
    area_id: UUID,
    area: dict[str, str],
    parent_id: UUID | None,
    counts: dict[str, int],
    registered_voters: int,
    totals: dict[str, int | None],
    contestant_votes: dict[UUID, int],
    contests: set[UUID],
    ballot: _Ballot,
    measure: Measure,
    updated_at: Any,
) -> dict[str, Any]:
    """One area's view: each party's votes side by side (with the contestant's name when the
    area is a single constituency), X of Y reported, and the leader status."""
    by_party: dict[UUID, int] = defaultdict(int)
    names: dict[UUID, tuple[UUID, str]] = {}
    for candidate_id, votes in contestant_votes.items():
        by_party[ballot.contestants[candidate_id][0]] += votes
    single = len(contests) == 1
    if single:
        (contest_id,) = contests
        for candidate_id, (party_id, cid, name) in ballot.contestants.items():
            if cid == contest_id:
                names[party_id] = (candidate_id, name)
    pos = position(by_party, ballot.parties, narrow_pct=_narrow_pct())
    abbreviations = {p.id: p.abbreviation for p in ballot.parties}
    expected = counts["expected_pus"]
    counted = counts["reported_pus"] if measure is Measure.REPORTED else counts["verified_pus"]
    return {
        "level": level,
        "area_id": area_id,
        "area_name": area["name"],
        "area_code": area["code"],
        "parent_id": parent_id,
        **counts,
        "reported_pct": coverage_pct(counts["reported_pus"], expected),
        "verified_pct": coverage_pct(counts["verified_pus"], expected),
        "counted_pus": counted,
        "registered_voters": registered_voters,
        "totals": totals,
        "votes": [
            {
                "party_id": p.id,
                "abbreviation": p.abbreviation,
                "candidate_id": names[p.id][0] if p.id in names else None,
                "candidate_name": names[p.id][1] if p.id in names else None,
                "votes": by_party.get(p.id, 0),
            }
            for p in ballot.parties
            # Within one constituency, list only the parties that field a contestant there.
            if not single or p.id in names
        ],
        "position": {
            "status": pos.status.value,
            "leader_party_id": pos.leader_id,
            "leader_abbreviation": abbreviations.get(pos.leader_id) if pos.leader_id else None,
            "runner_up_party_id": pos.runner_up_id,
            "leading_party_ids": list(pos.leading_ids),
            "margin": pos.margin,
            "margin_pct": pos.margin_pct,
            "total_votes": pos.total_votes,
            "is_tie": pos.is_tie,
            "own_margin": pos.own_margin,
        },
        "measure": measure.value,
        "updated_at": updated_at,
    }


def _visible(actor: Actor, election: Election) -> QuerySet[Rollup]:
    return Rollup.objects.for_actor(actor).filter(election=election)


def _fold(rows: list[Rollup], measure: Measure) -> dict[str, Any]:
    """Sum rollup rows (several contests and/or several areas) into one set of figures."""
    prefix = "reported" if measure is Measure.REPORTED else "verified"
    return {
        "counts": {name: sum(getattr(r, name) for r in rows) for name in _COUNTS},
        "registered_voters": sum(r.registered_voters for r in rows),
        "totals": {name: sum(getattr(r, f"{prefix}_{name}") for r in rows) for name in _SHEET},
        "contestant_votes": merge_votes(
            {
                v.candidate_id: v.reported_votes
                if measure is Measure.REPORTED
                else v.verified_votes
                for v in r.votes.all()
            }
            for r in rows
        ),
        "contests": {r.contest_id for r in rows},
        "updated_at": max((r.computed_at for r in rows), default=None),
    }


def _election_header(election: Election, ballot: _Ballot, measure: Measure) -> dict[str, Any]:
    return {
        "election_id": election.id,
        "election_name": election.name,
        "election_type": election.election_type.code,
        "election_type_name": election.election_type.name,
        "status": election.status,
        "measure": measure.value,
        "provisional": True,
        "notice": PROVISIONAL_NOTICE,
        "parties": ballot.party_views,
    }


def dashboard(actor: Actor, election: Election, measure: Measure) -> dict[str, Any]:
    """Headline figures for the election over everything the actor may see: every party side
    by side, the leader status, and X of Y polling units reported."""
    authorize(actor, Perm.DASHBOARD_VIEW)
    ballot = _ballot(actor, election)
    top = _SCOPE_TOP_LEVEL[actor.scope.kind]
    rows = list(_visible(actor, election).filter(level=top).prefetch_related("votes"))
    folded = _fold(rows, measure)
    areas = {r.area_id for r in rows}
    names = _area_names(top.value, areas)
    scope_label = "State" if actor.scope.kind is ScopeKind.ORG else actor.scope.kind.title()
    only = next(iter(areas)) if len(areas) == 1 else None
    summary = _compose(
        level=top.value,
        area_id=only or election.id,
        area=names.get(only, {"name": scope_label, "code": ""})
        if only
        else {"name": f"{scope_label} scope", "code": ""},
        parent_id=None,
        counts=folded["counts"],
        registered_voters=folded["registered_voters"],
        totals=folded["totals"],
        contestant_votes=folded["contestant_votes"],
        contests=folded["contests"],
        ballot=ballot,
        measure=measure,
        updated_at=folded["updated_at"],
    )
    return {
        **_election_header(election, ballot, measure),
        "summary": summary,
        "areas_in_scope": len(areas),
    }


def results(
    actor: Actor,
    election: Election,
    *,
    level: str | None,
    parent_id: UUID | None,
    measure: Measure,
) -> dict[str, Any]:
    """Drill-down rows for one election at one level, inside the actor's scope."""
    authorize(actor, Perm.DASHBOARD_VIEW)
    ballot = _ballot(actor, election)
    top = _SCOPE_TOP_LEVEL[actor.scope.kind]
    try:
        wanted = RollupLevel(level.upper()) if level else top
    except ValueError:
        raise ValidationError({"level": ["Use state, lga, ward or pu."]}) from None
    envelope = {
        **_election_header(election, ballot, measure),
        "level": wanted.value,
        "parent_id": parent_id,
    }
    if _ORDER.index(wanted) < _ORDER.index(top):
        # Above the actor's own level: nothing to show them, and nothing to reveal.
        return {**envelope, "rows": []}
    if wanted is RollupLevel.PU:
        if parent_id is None:
            raise ValidationError({"parent_id": ["Give the ward to list polling units for."]})
        return {**envelope, "rows": _pu_rows(actor, election, ballot, parent_id, measure)}
    if wanted is RollupLevel.WARD and parent_id is None and top is not RollupLevel.WARD:
        raise ValidationError({"parent_id": ["Give the LGA to list wards for."]})
    qs = _visible(actor, election).filter(level=wanted)
    if parent_id is not None:
        qs = qs.filter(parent_id=parent_id)
    by_area: dict[UUID, list[Rollup]] = defaultdict(list)
    for row in qs.prefetch_related("votes"):
        by_area[row.area_id].append(row)
    names = _area_names(wanted.value, by_area)
    views = []
    for area_id, rows in by_area.items():
        folded = _fold(rows, measure)
        views.append(
            _compose(
                level=wanted.value,
                area_id=area_id,
                area=names.get(area_id, {"name": "", "code": ""}),
                parent_id=rows[0].parent_id,
                counts=folded["counts"],
                registered_voters=folded["registered_voters"],
                totals=folded["totals"],
                contestant_votes=folded["contestant_votes"],
                contests=folded["contests"],
                ballot=ballot,
                measure=measure,
                updated_at=folded["updated_at"],
            )
        )
    views.sort(key=lambda v: (v["area_name"], str(v["area_id"])))
    return {**envelope, "rows": views}


def _pu_rows(
    actor: Actor, election: Election, ballot: _Ballot, ward_id: UUID, measure: Measure
) -> list[dict[str, Any]]:
    # The ward row is the scope check: invisible or uncovered wards are simply not found.
    if not _visible(actor, election).filter(level=RollupLevel.WARD, area_id=ward_id).exists():
        raise NotFound()
    contests = {c.constituency_id: c.id for c in elections.contests_for(actor, election)}
    # The ward's units that vote in this election: those whose constituency has a contest.
    units = (
        PollingUnit.objects.filter(
            ward_id=ward_id,
            constituencies__kind=election.election_type.constituency_kind,
            constituencies__constituency_id__in=list(contests),
        )
        .values("id", "name", "inec_code", "registered_voters", "constituencies__constituency_id")
        .order_by("inec_code")
    )
    results_by_pu = {
        r.polling_unit_id: r
        for r in PuResult.objects.for_actor(actor)
        .filter(election=election, ward_id=ward_id)
        .select_related("head_version")
    }
    head_ids = [r.head_version_id for r in results_by_pu.values() if r.head_version_id]
    votes_by_version: dict[UUID, dict[UUID, int]] = defaultdict(dict)
    for line in VoteLine.objects.filter(result_version_id__in=head_ids):
        votes_by_version[line.result_version_id][line.candidate_id] = line.votes
    evidence: dict[UUID, list[str]] = defaultdict(list)
    for version_id, status in (
        ResultVersion.objects.filter(id__in=head_ids)
        .values_list("id", "evidence__status")
        .exclude(evidence__status__isnull=True)
    ):
        evidence[version_id].append(status)
    flags: dict[UUID, int] = {
        row["polling_unit_id"]: row["n"]
        for row in AnomalyFlag.objects.for_actor(actor)
        .filter(election=election, ward_id=ward_id, status="OPEN")
        .values("polling_unit_id")
        .annotate(n=Count("id"))
    }
    reported_states = {s.value for s in REPORTED_STATES}
    verified_states = {s.value for s in VERIFIED_STATES}
    rows = []
    for unit in units:
        result = results_by_pu.get(unit["id"])
        head = result.head_version if result else None
        reported = head is not None and head.state in reported_states
        verified = head is not None and head.state in verified_states
        counted = verified if measure is Measure.VERIFIED else reported
        view = _compose(
            level="PU",
            area_id=unit["id"],
            area={"name": unit["name"], "code": unit["inec_code"]},
            parent_id=ward_id,
            counts={
                "expected_pus": 1,
                "reported_pus": int(reported),
                "verified_pus": int(verified),
                "review_pus": int(head is not None and head.state == "REQUIRES_REVIEW"),
                "open_flags": flags.get(unit["id"], 0),
            },
            registered_voters=unit["registered_voters"] or 0,
            totals={name: getattr(head, name) for name in _SHEET}
            if counted and head
            else {n: None for n in _SHEET},
            contestant_votes=votes_by_version.get(head.id, {}) if counted and head else {},
            contests={contests[unit["constituencies__constituency_id"]]},
            ballot=ballot,
            measure=measure,
            updated_at=head.server_received_at if head else None,
        )
        view["status"] = result.status if result else "NO_RESULT"
        view["head_version_id"] = result.head_version_id if result else None
        view["verified"] = verified
        view["completion"] = completion_of(evidence.get(head.id, [])) if head else None
        rows.append(view)
    return rows


def coverage_timeline(
    actor: Actor, election: Election, *, interval: str, parent_id: UUID | None
) -> dict[str, Any]:
    """Cumulative count of polling units that have reported, by time of first submission."""
    authorize(actor, Perm.DASHBOARD_VIEW)
    if interval not in {"minute", "hour"}:
        raise ValidationError({"interval": ["Use minute or hour."]})
    trunc = TruncMinute if interval == "minute" else TruncHour
    firsts = ResultVersion.objects.for_actor(actor).filter(
        pu_result__election=election, version_no=1
    )
    if parent_id is not None:
        firsts = firsts.filter(Q(ward_id=parent_id) | Q(lga_id=parent_id))
    buckets = (
        firsts.annotate(bucket=trunc("server_received_at"))
        .values("bucket")
        .annotate(n=Count("id"))
        .order_by("bucket")
    )
    expected = (
        _visible(actor, election)
        .filter(level=_SCOPE_TOP_LEVEL[actor.scope.kind])
        .values_list("expected_pus", flat=True)
    )
    running = 0
    points = []
    for row in buckets:
        running += row["n"]
        points.append({"at": row["bucket"], "newly_reported": row["n"], "cumulative": running})
    return {
        "election_id": election.id,
        "interval": interval,
        "expected_pus": sum(expected),
        "points": points,
    }
