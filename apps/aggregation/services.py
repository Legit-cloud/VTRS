"""Rollup maintenance, verification and reconciliation (FR-6.7.1, FR-6.7.2, AC-09, AC-10).

Rollups are recomputed, never incremented. A polling-unit event names the ward it touched; the
worker recalculates that ward from its head versions, then its LGA from the ward rows, then the
state from the LGA rows. Recomputing is idempotent and order-independent, so a duplicated,
delayed or lost event cannot leave a figure wrong for longer than the next event (or the next
`rebuild_rollups`). One advisory lock per contest serializes the three steps, so concurrent
workers never interleave a read of a child row with a write of its parent.
"""

import logging
from collections.abc import Iterable, Mapping
from typing import Any, cast
from uuid import UUID

from django.db import connection, transaction
from django.db.models import Count, F, Q, QuerySet, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.anomalies.models import AnomalyFlag
from apps.audit import services as audit
from apps.core import rls
from apps.core.authz import authorize
from apps.core.domain.actor import Actor
from apps.core.domain.canonical import payload_hash, to_json_compatible
from apps.core.domain.permissions import Perm
from apps.elections import selectors as elections
from apps.elections.models import Candidate, Contest, Election
from apps.geography.models import PollingUnit, Ward
from apps.results.domain.versions import REPORTED_STATES, VERIFIED_STATES
from apps.results.models import ResultVersion, VoteLine

from . import realtime
from .domain.tally import RollupLevel
from .errors import ReconciliationBlocked, RollupsDrifted
from .models import ReconciliationSnapshot, Rollup, RollupVote

logger = logging.getLogger("vtrs.aggregation")

REPORTED = sorted(s.value for s in REPORTED_STATES)
VERIFIED = sorted(s.value for s in VERIFIED_STATES)
SHEET = ("accredited", "valid", "rejected", "total_cast")
# Every additive column of a rollup row: a parent is the sum of its children on each.
FIGURES = (
    "expected_pus",
    "registered_voters",
    "reported_pus",
    "verified_pus",
    "review_pus",
    "open_flags",
    *(f"{measure}_{name}" for measure in ("reported", "verified") for name in SHEET),
)


def _lock_contest(contest_id: UUID) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [f"rollup:{contest_id}"]
        )


def _covered_wards(contest: Contest) -> QuerySet[Ward]:
    field = {"STATE": "state_id", "LGA": "lga_id", "WARD": "id"}[contest.jurisdiction_level]
    return Ward.objects.filter(**{f"{field}__in": contest.jurisdiction_ids})


def _heads(contest_id: UUID) -> QuerySet[ResultVersion]:
    """The version that currently counts for each polling unit of a contest."""
    return ResultVersion.objects.filter(contest_id=contest_id, pu_result__head_version_id=F("id"))


def _head_aggregates() -> dict[str, Any]:
    """Aggregate expressions shared by the ward calculation and the verification pass."""
    reported = Q(state__in=REPORTED)
    verified = Q(state__in=VERIFIED)
    aggregates: dict[str, Any] = {
        "reported_pus": Count("id", filter=reported),
        "verified_pus": Count("id", filter=verified),
        "review_pus": Count("id", filter=Q(state="REQUIRES_REVIEW")),
    }
    for name in SHEET:
        aggregates[f"reported_{name}"] = Coalesce(Sum(name, filter=reported), 0)
        aggregates[f"verified_{name}"] = Coalesce(Sum(name, filter=verified), 0)
    return aggregates


def _vote_aggregates(contest_id: UUID) -> QuerySet[VoteLine]:
    return VoteLine.objects.filter(
        result_version__contest_id=contest_id,
        result_version__pu_result__head_version_id=F("result_version_id"),
    )


def _vote_sums() -> dict[str, Any]:
    return {
        "reported": Coalesce(Sum("votes", filter=Q(result_version__state__in=REPORTED)), 0),
        "verified": Coalesce(Sum("votes", filter=Q(result_version__state__in=VERIFIED)), 0),
    }


# --- Writing rows -----------------------------------------------------------------------------


def _store(
    contest: Contest,
    *,
    level: RollupLevel,
    area_id: UUID,
    parent_id: UUID | None,
    lga_id: UUID | None,
    ward_id: UUID | None,
    figures: Mapping[str, int],
    votes: Mapping[UUID, tuple[int, int]],
    candidate_ids: Iterable[UUID],
    now: Any,
) -> Rollup:
    row = Rollup.objects.filter(contest=contest, level=level, area_id=area_id).first()
    if row is None:
        row = Rollup(
            organization_id=contest.organization_id,
            election_id=contest.election_id,
            contest=contest,
            level=level,
            area_id=area_id,
            revision=0,
        )
    row.parent_id = parent_id
    row.lga_id = lga_id
    row.ward_id = ward_id
    for name, value in figures.items():
        setattr(row, name, value)
    row.revision += 1
    row.computed_at = now
    row.save()

    existing = {v.candidate_id: v for v in row.votes.all()}
    to_create, to_update = [], []
    for candidate_id in candidate_ids:
        reported, verified = votes.get(candidate_id, (0, 0))
        vote = existing.get(candidate_id)
        if vote is None:
            to_create.append(
                RollupVote(
                    organization_id=contest.organization_id,
                    rollup=row,
                    candidate_id=candidate_id,
                    reported_votes=reported,
                    verified_votes=verified,
                )
            )
        elif (vote.reported_votes, vote.verified_votes) != (reported, verified):
            vote.reported_votes, vote.verified_votes = reported, verified
            to_update.append(vote)
    RollupVote.objects.bulk_create(to_create)
    RollupVote.objects.bulk_update(to_update, ["reported_votes", "verified_votes"])
    return row


def _compute_ward(contest: Contest, ward: Ward, candidate_ids: list[UUID], now: Any) -> Rollup:
    heads = _heads(contest.id).filter(ward_id=ward.id)
    figures: dict[str, int] = heads.aggregate(**_head_aggregates())
    units = PollingUnit.objects.filter(ward_id=ward.id).aggregate(
        n=Count("id"), registered=Coalesce(Sum("registered_voters"), 0)
    )
    figures["expected_pus"] = units["n"]
    figures["registered_voters"] = units["registered"]
    figures["open_flags"] = AnomalyFlag.objects.filter(
        contest_id=contest.id, ward_id=ward.id, status="OPEN"
    ).count()
    vote_rows = cast(
        Iterable[dict[str, Any]],
        _vote_aggregates(contest.id)
        .filter(result_version__ward_id=ward.id)
        .values("candidate_id")
        .annotate(**_vote_sums()),
    )
    votes = {row["candidate_id"]: (row["reported"], row["verified"]) for row in vote_rows}
    return _store(
        contest,
        level=RollupLevel.WARD,
        area_id=ward.id,
        parent_id=ward.lga_id,
        lga_id=ward.lga_id,
        ward_id=ward.id,
        figures=figures,
        votes=votes,
        candidate_ids=candidate_ids,
        now=now,
    )


def _sum_children(children: QuerySet[Rollup]) -> tuple[dict[str, int], dict[UUID, tuple[int, int]]]:
    names = list(FIGURES)
    figures = children.aggregate(**{n: Coalesce(Sum(n), 0) for n in names})
    vote_rows = cast(
        Iterable[dict[str, Any]],
        RollupVote.objects.filter(rollup__in=children)
        .values("candidate_id")
        .annotate(
            reported=Coalesce(Sum("reported_votes"), 0),
            verified=Coalesce(Sum("verified_votes"), 0),
        ),
    )
    votes = {row["candidate_id"]: (row["reported"], row["verified"]) for row in vote_rows}
    return figures, votes


def _compute_lga(contest: Contest, lga_id: UUID, candidate_ids: list[UUID], now: Any) -> Rollup:
    children = Rollup.objects.filter(contest=contest, level=RollupLevel.WARD, lga_id=lga_id)
    figures, votes = _sum_children(children)
    return _store(
        contest,
        level=RollupLevel.LGA,
        area_id=lga_id,
        parent_id=contest.election.state_id,
        lga_id=lga_id,
        ward_id=None,
        figures=figures,
        votes=votes,
        candidate_ids=candidate_ids,
        now=now,
    )


def _compute_state(contest: Contest, candidate_ids: list[UUID], now: Any) -> Rollup:
    children = Rollup.objects.filter(contest=contest, level=RollupLevel.LGA)
    figures, votes = _sum_children(children)
    return _store(
        contest,
        level=RollupLevel.STATE,
        area_id=contest.election.state_id,
        parent_id=None,
        lga_id=None,
        ward_id=None,
        figures=figures,
        votes=votes,
        candidate_ids=candidate_ids,
        now=now,
    )


# --- Entry points -----------------------------------------------------------------------------


def _open(organization_id: UUID, contest_id: UUID) -> tuple[Contest, list[UUID]] | None:
    rls.set_tenant(organization_id)
    _lock_contest(contest_id)
    contest = Contest.objects.select_related("election").filter(id=contest_id).first()
    if contest is None:
        return None
    candidate_ids = list(Candidate.objects.filter(contest=contest).values_list("id", flat=True))
    return contest, candidate_ids


def _rebuild(contest: Contest, candidate_ids: list[UUID]) -> int:
    """Rebuild every row of a contest in a handful of grouped queries and bulk writes.

    Used for the first build, repairs and reconciliation, where thousands of wards would make
    a ward-by-ward loop take minutes. The incremental path (`recompute_ward`) shares the
    rules but touches one ward."""
    now = timezone.now()
    wards = list(_covered_wards(contest))
    ward_ids = [w.id for w in wards]
    per_ward: dict[UUID, dict[str, int]] = {w.id: dict.fromkeys(FIGURES, 0) for w in wards}
    ward_votes: dict[UUID, dict[UUID, tuple[int, int]]] = {w.id: {} for w in wards}

    head_rows = cast(
        Iterable[dict[str, Any]],
        _heads(contest.id).values("ward_id").annotate(**_head_aggregates()),
    )
    for row in head_rows:
        if row["ward_id"] in per_ward:
            per_ward[row["ward_id"]].update({k: v for k, v in row.items() if k != "ward_id"})
    unit_rows = cast(
        Iterable[dict[str, Any]],
        PollingUnit.objects.filter(ward_id__in=ward_ids)
        .values("ward_id")
        .annotate(n=Count("id"), registered=Coalesce(Sum("registered_voters"), 0)),
    )
    for row in unit_rows:
        per_ward[row["ward_id"]]["expected_pus"] = row["n"]
        per_ward[row["ward_id"]]["registered_voters"] = row["registered"]
    flag_rows = cast(
        Iterable[dict[str, Any]],
        AnomalyFlag.objects.filter(contest_id=contest.id, status="OPEN")
        .values("ward_id")
        .annotate(n=Count("id")),
    )
    for row in flag_rows:
        if row["ward_id"] in per_ward:
            per_ward[row["ward_id"]]["open_flags"] = row["n"]
    vote_rows = cast(
        Iterable[dict[str, Any]],
        _vote_aggregates(contest.id)
        .values("result_version__ward_id", "candidate_id")
        .annotate(**_vote_sums()),
    )
    for row in vote_rows:
        ward_id = row["result_version__ward_id"]
        if ward_id in ward_votes:
            ward_votes[ward_id][row["candidate_id"]] = (row["reported"], row["verified"])

    # Parents are plain sums of their children.
    per_lga: dict[UUID, dict[str, int]] = {}
    lga_votes: dict[UUID, dict[UUID, tuple[int, int]]] = {}
    state_figures: dict[str, int] = dict.fromkeys(FIGURES, 0)
    state_votes: dict[UUID, tuple[int, int]] = {}

    def fold(
        into: dict[str, int],
        into_votes: dict[UUID, tuple[int, int]],
        figures: dict[str, int],
        votes: dict[UUID, tuple[int, int]],
    ) -> None:
        for name in FIGURES:
            into[name] += figures[name]
        for candidate_id, (reported, verified) in votes.items():
            have = into_votes.get(candidate_id, (0, 0))
            into_votes[candidate_id] = (have[0] + reported, have[1] + verified)

    for ward in wards:
        lga_figures = per_lga.setdefault(ward.lga_id, dict.fromkeys(FIGURES, 0))
        fold(
            lga_figures,
            lga_votes.setdefault(ward.lga_id, {}),
            per_ward[ward.id],
            ward_votes[ward.id],
        )
        fold(state_figures, state_votes, per_ward[ward.id], ward_votes[ward.id])

    state_id = contest.election.state_id
    planned: list[tuple[RollupLevel, UUID, UUID | None, UUID | None, UUID | None, Any, Any]] = [
        (RollupLevel.WARD, w.id, w.lga_id, w.lga_id, w.id, per_ward[w.id], ward_votes[w.id])
        for w in wards
    ]
    planned += [
        (RollupLevel.LGA, lga_id, state_id, lga_id, None, per_lga[lga_id], lga_votes[lga_id])
        for lga_id in per_lga
    ]
    planned.append((RollupLevel.STATE, state_id, None, None, None, state_figures, state_votes))
    _write_rows(contest, planned, candidate_ids, now)

    return len(wards)


def _write_rows(
    contest: Contest,
    planned: list[tuple[RollupLevel, UUID, UUID | None, UUID | None, UUID | None, Any, Any]],
    candidate_ids: list[UUID],
    now: Any,
) -> None:
    """Replace a contest's rows with the planned set.

    Delete-and-insert inside the caller's transaction is invisible to readers until commit and
    far cheaper than updating hundreds of rows field by field. It also drops rows for areas
    the contest no longer covers. `revision` carries on from the old row, so clients still
    see it move forward."""
    previous = {
        (level, area_id): revision
        for level, area_id, revision in Rollup.objects.filter(contest=contest).values_list(
            "level", "area_id", "revision"
        )
    }
    RollupVote.objects.filter(rollup__contest=contest).delete()
    Rollup.objects.filter(contest=contest).delete()

    rows: list[Rollup] = []
    votes_to_create: list[RollupVote] = []
    for level, area_id, parent_id, lga_id, ward_id, figures, votes in planned:
        row = Rollup(
            organization_id=contest.organization_id,
            election_id=contest.election_id,
            contest=contest,
            level=level.value,
            area_id=area_id,
            parent_id=parent_id,
            lga_id=lga_id,
            ward_id=ward_id,
            revision=previous.get((level.value, area_id), 0) + 1,
            computed_at=now,
            **{name: figures[name] for name in FIGURES},
        )
        rows.append(row)
        for candidate_id in candidate_ids:
            reported, verified = votes.get(candidate_id, (0, 0))
            votes_to_create.append(
                RollupVote(
                    organization_id=contest.organization_id,
                    rollup=row,
                    candidate_id=candidate_id,
                    reported_votes=reported,
                    verified_votes=verified,
                )
            )
    Rollup.objects.bulk_create(rows, batch_size=500)
    RollupVote.objects.bulk_create(votes_to_create, batch_size=1000)


def _is_complete(contest: Contest) -> bool:
    """Every covered ward and the state row exist, so summing child rows is safe."""
    wards = Rollup.objects.filter(contest=contest, level=RollupLevel.WARD).count()
    state = Rollup.objects.filter(
        contest=contest, level=RollupLevel.STATE, area_id=contest.election.state_id
    ).exists()
    return state and wards == _covered_wards(contest).count()


def recompute_ward(*, organization_id: UUID, contest_id: UUID, ward_id: UUID) -> dict[str, Any]:
    """Refresh one ward and the LGA and state above it. Safe to run any number of times.

    If the contest's rows are not all there yet (a result arrived before the worker built
    them), it builds them all instead, so a parent is never summed from a partial set."""
    with transaction.atomic():
        opened = _open(organization_id, contest_id)
        if opened is None:
            return {}
        contest, candidate_ids = opened
        ward = _covered_wards(contest).filter(id=ward_id).first()
        if ward is None:
            return {}
        if not _is_complete(contest):
            _rebuild(contest, candidate_ids)
        else:
            now = timezone.now()
            _compute_ward(contest, ward, candidate_ids, now)
            _compute_lga(contest, ward.lga_id, candidate_ids, now)
            _compute_state(contest, candidate_ids, now)
        state_row = Rollup.objects.get(
            contest=contest, level=RollupLevel.STATE, area_id=contest.election.state_id
        )
        election_id, lga_id, revision = contest.election_id, ward.lga_id, state_row.revision
        transaction.on_commit(
            lambda: realtime.announce(
                election_id=election_id,
                contest_id=contest_id,
                lga_id=lga_id,
                ward_id=ward_id,
                revision=revision,
            )
        )
        return {
            "contest_id": contest_id,
            "election_id": contest.election_id,
            "ward_id": ward.id,
            "lga_id": ward.lga_id,
            "state_id": contest.election.state_id,
            "state_revision": state_row.revision,
        }


def rebuild_contest(*, organization_id: UUID, contest_id: UUID) -> int:
    """Recalculate every row of a contest from head versions. Returns the number of wards."""
    with transaction.atomic():
        opened = _open(organization_id, contest_id)
        if opened is None:
            return 0
        contest, candidate_ids = opened
        return _rebuild(contest, candidate_ids)


def rebuild_election(election: Election) -> int:
    total = 0
    for contest_id in Contest.objects.filter(election=election).values_list("id", flat=True):
        total += rebuild_contest(organization_id=election.organization_id, contest_id=contest_id)
    return total


def ensure_contest_rows(contest: Contest) -> None:
    """Create rows for a contest that has none yet (a read on a freshly locked election)."""
    if not Rollup.objects.filter(contest=contest).exists():
        rebuild_contest(organization_id=contest.organization_id, contest_id=contest.id)


# --- Verification -----------------------------------------------------------------------------


def _blank_figures() -> dict[str, Any]:
    figures: dict[str, Any] = {
        name: 0 for name in ("expected_pus", "reported_pus", "verified_pus", "review_pus")
    }
    figures.update({f"{m}_{n}": 0 for m in ("reported", "verified") for n in SHEET})
    figures["votes"] = {}
    return figures


def _add_figures(target: dict[str, Any], source: Mapping[str, Any]) -> None:
    for name, value in source.items():
        if name == "votes":
            for candidate_id, (reported, verified) in value.items():
                have = target["votes"].get(candidate_id, (0, 0))
                target["votes"][candidate_id] = (have[0] + reported, have[1] + verified)
        else:
            target[name] += value


def verify_contest(contest: Contest) -> list[str]:
    """Compare stored rollups with a fresh calculation done straight from head versions.

    Returns one message per difference; an empty list means every figure reconciles.
    """
    wards = {w.id: w for w in _covered_wards(contest)}
    per_ward: dict[UUID, dict[str, Any]] = {ward_id: _blank_figures() for ward_id in wards}

    head_rows = cast(
        Iterable[dict[str, Any]],
        _heads(contest.id).values("ward_id").annotate(**_head_aggregates()),
    )
    for head in head_rows:
        if head["ward_id"] in per_ward:
            per_ward[head["ward_id"]].update({k: v for k, v in head.items() if k != "ward_id"})
    unit_rows = cast(
        Iterable[dict[str, Any]],
        PollingUnit.objects.filter(ward_id__in=wards).values("ward_id").annotate(n=Count("id")),
    )
    for unit in unit_rows:
        per_ward[unit["ward_id"]]["expected_pus"] = unit["n"]
    vote_rows = cast(
        Iterable[dict[str, Any]],
        _vote_aggregates(contest.id)
        .values("result_version__ward_id", "candidate_id")
        .annotate(**_vote_sums()),
    )
    for vote in vote_rows:
        ward_id = vote["result_version__ward_id"]
        if ward_id in per_ward:
            per_ward[ward_id]["votes"][vote["candidate_id"]] = (vote["reported"], vote["verified"])

    fresh: dict[tuple[str, UUID], dict[str, Any]] = {}
    per_lga: dict[UUID, dict[str, Any]] = {}
    state_total = _blank_figures()
    for ward_id, figures in per_ward.items():
        fresh[(RollupLevel.WARD.value, ward_id)] = figures
        _add_figures(per_lga.setdefault(wards[ward_id].lga_id, _blank_figures()), figures)
        _add_figures(state_total, figures)
    for lga_id, figures in per_lga.items():
        fresh[(RollupLevel.LGA.value, lga_id)] = figures
    fresh[(RollupLevel.STATE.value, contest.election.state_id)] = state_total

    stored = {
        (rollup.level, rollup.area_id): rollup
        for rollup in Rollup.objects.filter(contest=contest).prefetch_related("votes")
    }
    problems: list[str] = []
    for key in sorted(set(fresh) | set(stored), key=lambda k: (k[0], str(k[1]))):
        label = f"{key[0]} {key[1]}"
        if key not in stored:
            problems.append(f"{label}: missing rollup row")
            continue
        if key not in fresh:
            problems.append(f"{label}: rollup row for an area the contest does not cover")
            continue
        rollup, expected = stored[key], fresh[key]
        for name, value in expected.items():
            if name == "votes":
                have = {
                    v.candidate_id: (v.reported_votes, v.verified_votes) for v in rollup.votes.all()
                }
                for candidate_id in set(have) | set(value):
                    got = have.get(candidate_id, (0, 0))
                    want = value.get(candidate_id, (0, 0))
                    if got != want:
                        problems.append(
                            f"{label}: votes for {candidate_id} are {got}, expected {want}"
                        )
            elif getattr(rollup, name) != value:
                problems.append(f"{label}: {name} is {getattr(rollup, name)}, expected {value}")
    return problems


# --- Reconciliation ---------------------------------------------------------------------------


def readiness(actor: Actor, election: Election) -> dict[str, Any]:
    """What stands between a closed election and RECONCILED."""
    authorize(actor, Perm.ELECTIONS_CONFIGURE)
    contests = list(Contest.objects.filter(election=election))
    undecided = 0
    drift: list[str] = []
    for contest in contests:
        if election.review_enabled:
            undecided += (
                _heads(contest.id).filter(state__in=["SUBMITTED", "REQUIRES_REVIEW"]).count()
            )
        drift.extend(verify_contest(contest))
    snapshot = ReconciliationSnapshot.objects.filter(election=election).first()
    return {
        "election_id": election.id,
        "status": election.status,
        "review_enabled": election.review_enabled,
        "undecided_results": undecided,
        "rollup_differences": drift,
        "can_reconcile": election.status == "CLOSED" and undecided == 0,
        "reconciled_at": snapshot.reconciled_at if snapshot else None,
        "snapshot_sha256": snapshot.sha256 if snapshot else None,
    }


def _snapshot_rows(election: Election) -> list[dict[str, Any]]:
    rows = []
    for contest in Contest.objects.filter(election=election).order_by("id"):
        for row in (
            Rollup.objects.filter(contest=contest)
            .prefetch_related("votes")
            .order_by("level", "area_id")
        ):
            rows.append(
                {
                    "contest_id": contest.id,
                    "level": row.level,
                    "area_id": row.area_id,
                    "expected_pus": row.expected_pus,
                    "reported_pus": row.reported_pus,
                    "verified_pus": row.verified_pus,
                    "review_pus": row.review_pus,
                    "open_flags": row.open_flags,
                    **{
                        f"{measure}_{name}": getattr(row, f"{measure}_{name}")
                        for measure in ("reported", "verified")
                        for name in SHEET
                    },
                    "votes": {
                        str(v.candidate_id): {
                            "reported": v.reported_votes,
                            "verified": v.verified_votes,
                        }
                        for v in sorted(row.votes.all(), key=lambda v: str(v.candidate_id))
                    },
                }
            )
    return rows


def reconcile(actor: Actor, election: Election) -> ReconciliationSnapshot:
    """Freeze the rollups of a closed election. Called inside the transition's transaction.

    Refuses while review is on and any counting result is undecided. Rebuilds from head
    versions first, so the snapshot is the calculation and not whatever the workers had
    reached, then proves the rebuild agrees with a second independent pass.
    """
    authorize(actor, Perm.ELECTIONS_CONFIGURE)
    contests = list(Contest.objects.filter(election=election))
    if election.review_enabled:
        undecided = sum(
            _heads(c.id).filter(state__in=["SUBMITTED", "REQUIRES_REVIEW"]).count()
            for c in contests
        )
        if undecided:
            raise ReconciliationBlocked(
                f"{undecided} counting result(s) still need a review decision."
            )
    rebuild_election(election)
    differences = [p for contest in contests for p in verify_contest(contest)]
    if differences:
        raise RollupsDrifted({"differences": differences[:20]})

    rows = _snapshot_rows(election)
    data = to_json_compatible(
        {"election_id": election.id, "config_hash": election.config_hash, "rows": rows}
    )
    state_rows = [r for r in rows if r["level"] == RollupLevel.STATE]
    snapshot = ReconciliationSnapshot.objects.create(
        organization_id=election.organization_id,
        election=election,
        config_hash=election.config_hash,
        data=data,
        sha256=payload_hash(data),
        reported_pus=sum(r["reported_pus"] for r in state_rows),
        verified_pus=sum(r["verified_pus"] for r in state_rows),
        reconciled_by_id=actor.user_id,
        reconciled_at=timezone.now(),
    )
    audit.record(
        action="election.reconciled",
        object_type="election",
        object_id=election.id,
        actor=actor,
        diff={
            "snapshot_id": snapshot.id,
            "sha256": snapshot.sha256,
            "reported_pus": snapshot.reported_pus,
            "verified_pus": snapshot.verified_pus,
            "config_hash": election.config_hash,
        },
    )
    return snapshot


def rebuild_election_by_id(*, organization_id: UUID, election_id: UUID) -> int:
    """Worker entry point: build every row of every contest of an election."""
    with transaction.atomic():
        rls.set_tenant(organization_id)
        contest_ids = list(
            Contest.objects.filter(election_id=election_id).values_list("id", flat=True)
        )
    return sum(
        rebuild_contest(organization_id=organization_id, contest_id=contest_id)
        for contest_id in contest_ids
    )


def ensure_rows_for_contest(actor: Actor, contest_id: UUID) -> Contest:
    """Authorize a dashboard read of a contest and make sure its rollup rows exist."""
    authorize(actor, Perm.DASHBOARD_VIEW)
    contest = elections.contest_for(actor, contest_id)
    ensure_contest_rows(contest)
    return contest


def ensure_rows_for_election(actor: Actor, election: Election) -> None:
    authorize(actor, Perm.DASHBOARD_VIEW)
    for contest in elections.contests_for(actor, election):
        ensure_contest_rows(contest)
