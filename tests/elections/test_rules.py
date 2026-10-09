import pytest

from apps.core.ids import uuid7
from apps.elections.domain.rules import (
    CandidateSpec,
    ContestSpec,
    ElectionStatus,
    JurisdictionLevel,
    can_transition,
    configuration_problems,
    covers,
    fingerprint,
    sheet_field_problems,
)

S = ElectionStatus


@pytest.mark.parametrize(
    ("current", "target", "allowed"),
    [
        (S.DRAFT, S.CONFIGURED, True),
        (S.CONFIGURED, S.DRAFT, True),
        (S.CONFIGURED, S.LOCKED, True),
        (S.LOCKED, S.LIVE, True),
        (S.LIVE, S.CLOSED, True),
        (S.DRAFT, S.LOCKED, False),
        (S.DRAFT, S.LIVE, False),
        (S.LOCKED, S.DRAFT, False),  # no unlocking
        (S.LOCKED, S.CONFIGURED, False),
        (S.LIVE, S.LOCKED, False),
        (S.CLOSED, S.LIVE, False),  # no reopening
        (S.CLOSED, S.RECONCILED, False),  # arrives with aggregation (M4)
    ],
)
def test_lifecycle(current, target, allowed):
    assert can_transition(current, target) is allowed


def _candidate(order, own=False):
    return CandidateSpec(uuid7(), f"C{order}", f"P{order}", order, own)


def _contest(candidates, ids=None, sheet=("accredited", "valid", "rejected", "total_cast")):
    return ContestSpec(
        id=uuid7(),
        office="GOVERNORSHIP",
        title="Governor",
        jurisdiction_level="STATE",
        jurisdiction_ids=tuple(ids if ids is not None else [uuid7()]),
        sheet_fields=tuple(sheet),
        candidates=tuple(candidates),
    )


def test_configuration_problems():
    assert configuration_problems([]) == ["the election has no contests"]
    assert configuration_problems([_contest([_candidate(1), _candidate(2)])]) == []
    problems = configuration_problems(
        [_contest([_candidate(1, own=True), _candidate(2, own=True)], ids=[], sheet=("rejected",))]
    )
    assert any("no jurisdiction" in p for p in problems)
    assert any("more than one candidate as the party's own" in p for p in problems)
    assert any("must include ['valid']" in p for p in problems)
    assert any(
        "at least two candidates" in p for p in configuration_problems([_contest([_candidate(1)])])
    )


def test_sheet_fields():
    assert sheet_field_problems(["valid"]) == []
    assert sheet_field_problems(["valid", "valid"]) == ["result fields repeat"]
    assert "unknown result field 'turnout'" in sheet_field_problems(["valid", "turnout"])


def test_coverage_by_level():
    state, lga, ward = uuid7(), uuid7(), uuid7()
    where = {"state_id": state, "lga_id": lga, "ward_id": ward}
    assert covers(JurisdictionLevel.STATE, [state], **where)
    assert covers(JurisdictionLevel.LGA, [uuid7(), lga], **where)  # e.g. a senatorial district
    assert covers(JurisdictionLevel.WARD, [ward], **where)
    assert not covers(JurisdictionLevel.LGA, [uuid7()], **where)
    assert not covers(JurisdictionLevel.WARD, [lga], **where)


def test_fingerprint_is_order_independent_and_change_sensitive():
    election = uuid7()
    a = _contest([_candidate(1), _candidate(2)])
    b = _contest([_candidate(1), _candidate(2)])
    assert fingerprint(election, [a, b]) == fingerprint(election, [b, a])
    renamed = ContestSpec(**{**a.__dict__, "title": "Governor (changed)"})
    assert fingerprint(election, [renamed, b]) != fingerprint(election, [a, b])
