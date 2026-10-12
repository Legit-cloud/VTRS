"""Dashboard reads (FR-6.8.1 - FR-6.8.4). Every read is narrowed to the actor's geography.

A scoped officer's top level is their own area: LGA officers start at their LGAs, ward officers
at their wards. The state total is not shown to them, because it includes areas they may not
see (spec section 8). Figures are provisional and carry `PROVISIONAL_NOTICE`.
"""

from collections import defaultdict
from collections.abc import Iterable
from typing import Any
from uuid import UUID

from django.db.models import Count, Q, QuerySet
from django.db.models.functions import TruncHour, TruncMinute
from rest_framework.exceptions import NotFound, ValidationError

from apps.anomalies.models import AnomalyFlag
from apps.core.authz import authorize
from apps.core.domain.actor import Actor, ScopeKind
from apps.core.domain.permissions import Perm
from apps.elections import selectors as elections
from apps.elections.models import Candidate, Contest, Election
from apps.geography.models import Lga, PollingUnit, State, Ward
from apps.results.domain.versions import REPORTED_STATES, VERIFIED_STATES
from apps.results.models import PuResult, ResultVersion, VoteLine

from .domain.tally import (
    PROVISIONAL_NOTICE,
    CandidateInfo,
    Measure,
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


def default_measure(election: Election) -> Measure:
    return Measure(election.count_policy)


def parse_measure(raw: str | None, election: Election) -> Measure:
    if raw is None:
        return default_measure(election)
    try:
        return Measure(raw.upper())
    except ValueError:
        raise ValidationError({"measure": ["Use reported or verified."]}) from None


def _candidates(contest: Contest) -> list[CandidateInfo]:
    return [
        CandidateInfo(c.id, c.name, c.party_acronym, c.ballot_order, c.is_own_party)
        for c in Candidate.objects.filter(contest=contest).order_by("ballot_order")
    ]


def _area_names(rows: Iterable[Rollup]) -> dict[UUID, dict[str, str]]:
    ids: dict[str, set[UUID]] = defaultdict(set)
    for row in rows:
        ids[row.level].add(row.area_id)
    names: dict[UUID, dict[str, str]] = {}
    for model, key in ((State, "STATE"), (Lga, "LGA"), (Ward, "WARD")):
        if ids[key]:
            for obj in model.objects.filter(id__in=ids[key]):
                names[obj.id] = {"name": obj.name, "code": obj.inec_code}
    return names


def _row_view(
    row: Rollup,
    measure: Measure,
    candidates: list[CandidateInfo],
    names: dict[UUID, dict[str, str]],
) -> dict[str, Any]:
    prefix = "reported" if measure is Measure.REPORTED else "verified"
    votes = {
        v.candidate_id: v.reported_votes if measure is Measure.REPORTED else v.verified_votes
        for v in row.votes.all()
    }
    return _compose(
        level=row.level,
        area_id=row.area_id,
        area=names.get(row.area_id, {"name": "", "code": ""}),
        parent_id=row.parent_id,
        expected_pus=row.expected_pus,
        reported_pus=row.reported_pus,
        verified_pus=row.verified_pus,
        review_pus=row.review_pus,
        open_flags=row.open_flags,
        registered_voters=row.registered_voters,
        totals={name: getattr(row, f"{prefix}_{name}") for name in _SHEET},
        votes=votes,
        candidates=candidates,
        measure=measure,
        updated_at=row.computed_at,
        revision=row.revision,
    )


def _compose(
    *,
    level: str,
    area_id: UUID,
    area: dict[str, str],
    parent_id: UUID | None,
    expected_pus: int,
    reported_pus: int,
    verified_pus: int,
    review_pus: int,
    open_flags: int,
    registered_voters: int,
    totals: dict[str, int | None],
    votes: dict[UUID, int],
    candidates: list[CandidateInfo],
    measure: Measure,
    updated_at: Any,
    revision: int | None,
) -> dict[str, Any]:
    pos = position(votes, candidates)
    by_id = {c.id: c for c in candidates}
    counted = reported_pus if measure is Measure.REPORTED else verified_pus
    return {
        "level": level,
        "area_id": area_id,
        "area_name": area["name"],
        "area_code": area["code"],
        "parent_id": parent_id,
        "expected_pus": expected_pus,
        "reported_pus": reported_pus,
        "verified_pus": verified_pus,
        "review_pus": review_pus,
        "reported_pct": coverage_pct(reported_pus, expected_pus),
        "verified_pct": coverage_pct(verified_pus, expected_pus),
        "counted_pus": counted,
        "open_flags": open_flags,
        "registered_voters": registered_voters,
        "totals": totals,
        "votes": [
            {
                "candidate_id": c.id,
                "party_acronym": c.party_acronym,
                "name": c.name,
                "votes": votes.get(c.id, 0),
            }
            for c in candidates
        ],
        "position": {
            "leader_id": pos.leader_id,
            "leader_party": by_id[pos.leader_id].party_acronym if pos.leader_id else None,
            "runner_up_id": pos.runner_up_id,
            "leading_ids": list(pos.leading_ids),
            "margin": pos.margin,
            "margin_pct": pos.margin_pct,
            "total_votes": pos.total_votes,
            "is_tie": pos.is_tie,
            "own_margin": pos.own_margin,
        },
        "measure": measure.value,
        "updated_at": updated_at,
        "revision": revision,
    }


def _contest_for_dashboard(actor: Actor, contest_id: UUID) -> Contest:
    authorize(actor, Perm.DASHBOARD_VIEW)
    return elections.contest_for(actor, contest_id)


def _visible(actor: Actor, contest: Contest) -> QuerySet[Rollup]:
    return Rollup.objects.for_actor(actor).filter(contest=contest)


def contest_summary(actor: Actor, contest: Contest, measure: Measure) -> dict[str, Any]:
    """One contest's headline figures over everything the actor may see."""
    top = _visible(actor, contest).filter(level=_SCOPE_TOP_LEVEL[actor.scope.kind])
    rows = list(top.prefetch_related("votes"))
    candidates = _candidates(contest)
    prefix = "reported" if measure is Measure.REPORTED else "verified"
    votes = merge_votes(
        {
            v.candidate_id: v.reported_votes if measure is Measure.REPORTED else v.verified_votes
            for v in row.votes.all()
        }
        for row in rows
    )
    totals = {name: sum(getattr(r, f"{prefix}_{name}") for r in rows) for name in _SHEET}
    area_names = _area_names(rows)
    scope_label = "State" if actor.scope.kind is ScopeKind.ORG else actor.scope.kind.title()
    summary = _compose(
        level=_SCOPE_TOP_LEVEL[actor.scope.kind].value,
        area_id=rows[0].area_id if len(rows) == 1 else contest.election_id,
        area={
            "name": area_names.get(rows[0].area_id, {}).get("name", scope_label)
            if len(rows) == 1
            else f"{scope_label} scope",
            "code": area_names.get(rows[0].area_id, {}).get("code", "") if len(rows) == 1 else "",
        },
        parent_id=None,
        expected_pus=sum(r.expected_pus for r in rows),
        reported_pus=sum(r.reported_pus for r in rows),
        verified_pus=sum(r.verified_pus for r in rows),
        review_pus=sum(r.review_pus for r in rows),
        open_flags=sum(r.open_flags for r in rows),
        registered_voters=sum(r.registered_voters for r in rows),
        totals=totals,
        votes=votes,
        candidates=candidates,
        measure=measure,
        updated_at=max((r.computed_at for r in rows), default=None),
        revision=None,
    )
    summary.update(
        {
            "contest_id": contest.id,
            "office": contest.office,
            "title": contest.title,
            "areas_in_scope": len(rows),
        }
    )
    return summary


def dashboard(actor: Actor, election: Election, measure: Measure) -> dict[str, Any]:
    authorize(actor, Perm.DASHBOARD_VIEW)
    contests = list(elections.contests_for(actor, election))
    return {
        "election_id": election.id,
        "election_name": election.name,
        "status": election.status,
        "measure": measure.value,
        "review_enabled": election.review_enabled,
        "provisional": True,
        "notice": PROVISIONAL_NOTICE,
        "contests": [contest_summary(actor, c, measure) for c in contests],
    }


def results(
    actor: Actor,
    contest_id: UUID,
    *,
    level: str | None,
    parent_id: UUID | None,
    measure_raw: str | None,
) -> dict[str, Any]:
    """Drill-down rows for one contest at one level, inside the actor's scope."""
    contest = _contest_for_dashboard(actor, contest_id)
    measure = parse_measure(measure_raw, contest.election)
    top = _SCOPE_TOP_LEVEL[actor.scope.kind]
    try:
        wanted = RollupLevel(level.upper()) if level else top
    except ValueError:
        raise ValidationError({"level": ["Use state, lga, ward or pu."]}) from None
    order = [RollupLevel.STATE, RollupLevel.LGA, RollupLevel.WARD, RollupLevel.PU]
    if order.index(wanted) < order.index(top):
        # Above the actor's own level: nothing to show them, and nothing to reveal.
        rows_out: list[dict[str, Any]] = []
        return _envelope(contest, wanted, parent_id, measure, rows_out)
    if wanted is RollupLevel.PU:
        if parent_id is None:
            raise ValidationError({"parent_id": ["Give the ward to list polling units for."]})
        return _envelope(
            contest, wanted, parent_id, measure, _pu_rows(actor, contest, parent_id, measure)
        )
    if wanted is RollupLevel.WARD and parent_id is None and top is not RollupLevel.WARD:
        raise ValidationError({"parent_id": ["Give the LGA to list wards for."]})
    qs = _visible(actor, contest).filter(level=wanted)
    if parent_id is not None:
        qs = qs.filter(parent_id=parent_id)
    rows = list(qs.prefetch_related("votes").order_by("area_id"))
    candidates = _candidates(contest)
    names = _area_names(rows)
    views = [_row_view(r, measure, candidates, names) for r in rows]
    views.sort(key=lambda v: (v["area_name"], str(v["area_id"])))
    return _envelope(contest, wanted, parent_id, measure, views)


def _envelope(
    contest: Contest,
    level: RollupLevel,
    parent_id: UUID | None,
    measure: Measure,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "contest_id": contest.id,
        "level": level.value,
        "parent_id": parent_id,
        "measure": measure.value,
        "provisional": True,
        "notice": PROVISIONAL_NOTICE,
        "rows": rows,
    }


def _pu_rows(
    actor: Actor, contest: Contest, ward_id: UUID, measure: Measure
) -> list[dict[str, Any]]:
    # The ward row is the scope check: invisible or uncovered wards are simply not found.
    if not _visible(actor, contest).filter(level=RollupLevel.WARD, area_id=ward_id).exists():
        raise NotFound()
    candidates = _candidates(contest)
    results_by_pu = {
        r.polling_unit_id: r
        for r in PuResult.objects.for_actor(actor)
        .filter(contest=contest, ward_id=ward_id)
        .select_related("head_version")
    }
    head_ids = [r.head_version_id for r in results_by_pu.values() if r.head_version_id]
    votes_by_version: dict[UUID, dict[UUID, int]] = defaultdict(dict)
    for line in VoteLine.objects.filter(result_version_id__in=head_ids):
        votes_by_version[line.result_version_id][line.candidate_id] = line.votes
    flags: dict[UUID, int] = {
        row["polling_unit_id"]: row["n"]
        for row in AnomalyFlag.objects.for_actor(actor)
        .filter(contest=contest, ward_id=ward_id, status="OPEN")
        .values("polling_unit_id")
        .annotate(n=Count("id"))
    }
    rows = []
    for pu in PollingUnit.objects.filter(ward_id=ward_id).order_by("inec_code"):
        result = results_by_pu.get(pu.id)
        head = result.head_version if result else None
        counted = head is not None and (
            head.state in {s.value for s in REPORTED_STATES}
            if measure is Measure.REPORTED
            else head.state in {s.value for s in VERIFIED_STATES}
        )
        reported = head is not None and head.state in {s.value for s in REPORTED_STATES}
        verified = head is not None and head.state in {s.value for s in VERIFIED_STATES}
        view = _compose(
            level="PU",
            area_id=pu.id,
            area={"name": pu.name, "code": pu.inec_code},
            parent_id=ward_id,
            expected_pus=1,
            reported_pus=int(reported),
            verified_pus=int(verified),
            review_pus=int(head is not None and head.state == "REQUIRES_REVIEW"),
            open_flags=flags.get(pu.id, 0),
            registered_voters=pu.registered_voters or 0,
            totals={name: getattr(head, name) for name in _SHEET}
            if counted and head
            else {n: None for n in _SHEET},
            votes=votes_by_version.get(head.id, {}) if counted and head else {},
            candidates=candidates,
            measure=measure,
            updated_at=head.server_received_at if head else None,
            revision=head.version_no if head else None,
        )
        view["status"] = result.status if result else "NO_RESULT"
        view["head_version_id"] = result.head_version_id if result else None
        rows.append(view)
    return rows


def coverage_timeline(
    actor: Actor, contest_id: UUID, *, interval: str, parent_id: UUID | None
) -> dict[str, Any]:
    """Cumulative count of polling units that have reported, by time of first submission."""
    contest = _contest_for_dashboard(actor, contest_id)
    if interval not in {"minute", "hour"}:
        raise ValidationError({"interval": ["Use minute or hour."]})
    trunc = TruncMinute if interval == "minute" else TruncHour
    firsts = ResultVersion.objects.for_actor(actor).filter(contest=contest, version_no=1)
    if parent_id is not None:
        firsts = firsts.filter(Q(ward_id=parent_id) | Q(lga_id=parent_id))
    buckets = (
        firsts.annotate(bucket=trunc("server_received_at"))
        .values("bucket")
        .annotate(n=Count("id"))
        .order_by("bucket")
    )
    expected = (
        _visible(actor, contest)
        .filter(level=_SCOPE_TOP_LEVEL[actor.scope.kind])
        .values_list("expected_pus", flat=True)
    )
    running = 0
    points = []
    for row in buckets:
        running += row["n"]
        points.append({"at": row["bucket"], "newly_reported": row["n"], "cumulative": running})
    return {
        "contest_id": contest.id,
        "interval": interval,
        "expected_pus": sum(expected),
        "points": points,
    }
