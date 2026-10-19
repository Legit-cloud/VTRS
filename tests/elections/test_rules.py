import pytest

from apps.core.ids import uuid7
from apps.elections.domain.rules import (
    ContestantSpec,
    ContestSpec,
    ElectionStatus,
    PartySpec,
    can_transition,
    configuration_problems,
    fingerprint,
    normalize_abbreviation,
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
        (S.CLOSED, S.RECONCILED, True),
        (S.RECONCILED, S.CLOSED, False),  # reconciliation is final
        (S.LIVE, S.RECONCILED, False),  # polls must close first
    ],
)
def test_lifecycle(current, target, allowed):
    assert can_transition(current, target) is allowed


def _parties(n=2):
    return [PartySpec(uuid7(), f"P{i}", i) for i in range(1, n + 1)]


def _contest(parties, name="Oyo"):
    return ContestSpec(
        id=uuid7(),
        constituency_id=uuid7(),
        constituency_name=name,
        contestants=tuple(
            ContestantSpec(uuid7(), f"C{p.ballot_order}", p.party_id) for p in parties
        ),
    )


def test_configuration_problems():
    parties = _parties()
    assert configuration_problems(parties, [_contest(parties)]) == []
    assert "no constituency has contestants yet" in configuration_problems(parties, [])
    assert any(
        "at least two contesting parties" in p
        for p in configuration_problems(parties[:1], [_contest(parties[:1])])
    )
    lonely = configuration_problems(parties, [_contest(parties[:1], "Lonely")])
    assert any("'Lonely' needs contestants from at least two parties" in p for p in lonely)
    stray = _contest([*parties, PartySpec(uuid7(), "XX", 9)], "Stray")
    assert any("party not contesting" in p for p in configuration_problems(parties, [stray]))


def test_abbreviations_are_normalized():
    assert normalize_abbreviation(" apc ") == "APC"


def test_fingerprint_is_order_independent_and_change_sensitive():
    election = uuid7()
    parties = _parties()
    a, b = _contest(parties, "A"), _contest(parties, "B")
    assert fingerprint(election, parties, [a, b]) == fingerprint(election, parties, [b, a])
    renamed = ContestSpec(
        a.id,
        a.constituency_id,
        a.constituency_name,
        (
            ContestantSpec(a.contestants[0].id, "Changed", a.contestants[0].party_id),
            *a.contestants[1:],
        ),
    )
    assert fingerprint(election, parties, [renamed, b]) != fingerprint(election, parties, [a, b])
    reordered = [PartySpec(p.party_id, p.abbreviation, 3 - p.ballot_order) for p in parties]
    assert fingerprint(election, reordered, [a, b]) != fingerprint(election, parties, [a, b])
