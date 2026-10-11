"""Leader, margin and coverage arithmetic (FR-6.8.2, FR-6.8.4)."""

import pytest

from apps.aggregation.domain.tally import (
    PROVISIONAL_NOTICE,
    CandidateInfo,
    coverage_pct,
    merge_votes,
    position,
)
from apps.core.ids import uuid7


def _candidates(*own_flags):
    return [
        CandidateInfo(uuid7(), f"Candidate {i}", f"P{i}", i, own)
        for i, own in enumerate(own_flags, start=1)
    ]


def test_leader_and_margin():
    a, b, c = _candidates(True, False, False)
    pos = position({a.id: 500, b.id: 320, c.id: 80}, [a, b, c])
    assert pos.leader_id == a.id
    assert pos.runner_up_id == b.id
    assert pos.margin == 180
    assert pos.margin_pct == 20.0
    assert pos.total_votes == 900
    assert pos.is_tie is False
    assert pos.own_margin == 180


def test_trailing_own_candidate_has_a_negative_margin():
    a, b = _candidates(True, False)
    pos = position({a.id: 100, b.id: 130}, [a, b])
    assert pos.leader_id == b.id
    assert pos.own_margin == -30


def test_a_tie_has_no_leader_and_no_margin():
    a, b, c = _candidates(False, False, False)
    pos = position({a.id: 200, b.id: 200, c.id: 10}, [a, b, c])
    assert pos.is_tie is True
    assert pos.leader_id is None
    assert set(pos.leading_ids) == {a.id, b.id}
    assert pos.margin == 0


def test_no_votes_means_no_position():
    a, b = _candidates(False, False)
    pos = position({}, [a, b])
    assert pos.leader_id is None
    assert pos.margin_pct is None
    assert pos.total_votes == 0
    assert pos.is_tie is False


def test_no_own_party_candidate_means_no_own_margin():
    a, b = _candidates(False, False)
    assert position({a.id: 5, b.id: 3}, [a, b]).own_margin is None


def test_coverage_handles_empty_areas():
    assert coverage_pct(0, 0) == 0.0
    assert coverage_pct(3, 8) == 37.5
    assert coverage_pct(8, 8) == 100.0


def test_merge_votes_sums_per_candidate():
    x, y = uuid7(), uuid7()
    assert merge_votes([{x: 1, y: 2}, {x: 10}, {}]) == {x: 11, y: 2}


def test_the_notice_says_it_is_not_official():
    assert "not an official declaration" in PROVISIONAL_NOTICE.lower()


@pytest.mark.parametrize("votes", [(0, 0), (1, 0), (7, 7)])
def test_margin_never_exceeds_the_leaders_votes(votes):
    a, b = _candidates(False, False)
    pos = position({a.id: votes[0], b.id: votes[1]}, [a, b])
    assert 0 <= pos.margin <= max(votes)
