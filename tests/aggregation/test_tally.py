"""Leader status, margin and coverage arithmetic (FR-6.8.2 - FR-6.8.6)."""

import pytest

from apps.aggregation.domain.tally import (
    PROVISIONAL_NOTICE,
    LeaderStatus,
    PartyInfo,
    coverage_pct,
    merge_votes,
    position,
)
from apps.core.ids import uuid7

NARROW = 5.0


def _parties(*own_flags):
    return [PartyInfo(uuid7(), f"P{i}", i, own) for i, own in enumerate(own_flags, start=1)]


def test_leader_and_margin():
    a, b, c = _parties(True, False, False)
    pos = position({a.id: 500, b.id: 320, c.id: 80}, [a, b, c], narrow_pct=NARROW)
    assert pos.status is LeaderStatus.LEADING
    assert pos.leader_id == a.id
    assert pos.runner_up_id == b.id
    assert pos.margin == 180
    assert pos.margin_pct == 20.0
    assert pos.total_votes == 900
    assert pos.is_tie is False
    assert pos.own_margin == 180


def test_trailing_own_party_has_a_negative_margin():
    a, b = _parties(True, False)
    pos = position({a.id: 100, b.id: 130}, [a, b], narrow_pct=NARROW)
    assert pos.leader_id == b.id
    assert pos.own_margin == -30


def test_a_tie_names_no_leader():
    a, b, c = _parties(False, False, False)
    pos = position({a.id: 200, b.id: 200, c.id: 10}, [a, b, c], narrow_pct=NARROW)
    assert pos.status is LeaderStatus.TIED
    assert pos.is_tie is True
    assert pos.leader_id is None
    assert set(pos.leading_ids) == {a.id, b.id}
    assert pos.margin == 0


def test_a_three_way_tie():
    a, b, c = _parties(False, False, False)
    pos = position({a.id: 9, b.id: 9, c.id: 9}, [a, b, c], narrow_pct=NARROW)
    assert pos.status is LeaderStatus.TIED
    assert set(pos.leading_ids) == {a.id, b.id, c.id}


@pytest.mark.parametrize(
    ("votes", "status"),
    [
        ((510, 490), LeaderStatus.NARROW),  # 2% of 1,000
        ((525, 475), LeaderStatus.NARROW),  # exactly 5%
        ((526, 474), LeaderStatus.LEADING),  # 5.2%
        ((1, 0), LeaderStatus.LEADING),  # 100%
    ],
)
def test_narrow_margins_are_named(votes, status):
    a, b = _parties(False, False)
    pos = position({a.id: votes[0], b.id: votes[1]}, [a, b], narrow_pct=NARROW)
    assert pos.status is status
    assert pos.leader_id == a.id  # a narrow lead still has a leader; the status says how close


def test_the_threshold_is_configurable():
    a, b = _parties(False, False)
    votes = {a.id: 540, b.id: 460}  # 8%
    assert position(votes, [a, b], narrow_pct=NARROW).status is LeaderStatus.LEADING
    assert position(votes, [a, b], narrow_pct=10).status is LeaderStatus.NARROW


def test_no_votes_means_no_position():
    a, b = _parties(False, False)
    pos = position({}, [a, b], narrow_pct=NARROW)
    assert pos.status is LeaderStatus.NO_VOTES
    assert pos.leader_id is None
    assert pos.margin_pct is None
    assert pos.total_votes == 0
    assert pos.is_tie is False


def test_no_own_party_means_no_own_margin():
    a, b = _parties(False, False)
    assert position({a.id: 5, b.id: 3}, [a, b], narrow_pct=NARROW).own_margin is None


def test_coverage_handles_empty_areas():
    assert coverage_pct(0, 0) == 0.0
    assert coverage_pct(3, 8) == 37.5
    assert coverage_pct(8, 8) == 100.0


def test_merge_votes_sums_per_party():
    x, y = uuid7(), uuid7()
    assert merge_votes([{x: 1, y: 2}, {x: 10}, {}]) == {x: 11, y: 2}


def test_the_notice_says_it_is_not_the_official_count():
    notice = PROVISIONAL_NOTICE.lower()
    assert "not the official inec count" in notice
    assert "own agents" in notice


@pytest.mark.parametrize("votes", [(0, 0), (1, 0), (7, 7)])
def test_margin_never_exceeds_the_leaders_votes(votes):
    a, b = _parties(False, False)
    pos = position({a.id: votes[0], b.id: votes[1]}, [a, b], narrow_pct=NARROW)
    assert 0 <= pos.margin <= max(votes)
