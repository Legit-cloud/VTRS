"""A burst of results is one refresh, not one per result (AC-15)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.aggregation import services
from apps.aggregation.models import Rollup, RollupDirty
from apps.core.rls import system_context

pytestmark = pytest.mark.django_db


def _state(field):
    with system_context():
        return Rollup.objects.get(
            contest=field.contest, level="STATE", area_id=field.election.state_id
        )


def _args(field, ward):
    return {
        "organization_id": field.org.id,
        "contest_id": field.contest.id,
        "ward_id": ward.id,
    }


def test_many_marks_are_one_refresh(field_):
    f = field_
    for index, pu in enumerate(f.pus):
        f.submit(pu, (10 + index, 5))
    before = _state(f).revision
    for ward in f.wards:
        services.mark_dirty(**_args(f, ward))
    with system_context():
        assert RollupDirty.objects.count() == 4

    result = services.drain_contest(organization_id=f.org.id, contest_id=f.contest.id)
    assert result["wards_refreshed"] == 4
    assert _state(f).revision == before + 1  # the state was refreshed once, not four times
    with system_context():
        assert RollupDirty.objects.count() == 0
        assert services.verify_contest(f.contest) == []


def test_draining_nothing_does_nothing(field_):
    f = field_
    f.submit(f.pus[0])
    before = _state(f).revision
    assert services.drain_contest(organization_id=f.org.id, contest_id=f.contest.id) == {}
    assert _state(f).revision == before


def test_a_second_drain_finds_the_work_already_done(field_):
    f = field_
    f.submit(f.pus[0])
    services.mark_dirty(**_args(f, f.wards[0]))
    first = services.drain_contest(organization_id=f.org.id, contest_id=f.contest.id)
    second = services.drain_contest(organization_id=f.org.id, contest_id=f.contest.id)
    assert first["wards_refreshed"] == 1 and second == {}


def test_marks_a_dead_worker_left_behind_are_swept(field_):
    f = field_
    f.submit(f.pus[0], (100, 40))
    # Simulate the figures changing without the event being processed.
    services.mark_dirty(**_args(f, f.pus[0].ward))
    with system_context():
        RollupDirty.objects.update(marked_at=timezone.now() - timedelta(minutes=5))
        Rollup.objects.filter(contest=f.contest, level="STATE").update(reported_valid=0)
    assert services.drain_stale(older_than_seconds=20) == 1
    assert _state(f).reported_valid == 140


def test_fresh_marks_are_left_for_their_own_worker(field_):
    f = field_
    f.submit(f.pus[0])
    services.mark_dirty(**_args(f, f.wards[1]))
    assert services.drain_stale(older_than_seconds=60) == 0
    with system_context():
        assert RollupDirty.objects.count() == 1


def test_a_full_rebuild_settles_every_mark(field_):
    f = field_
    f.submit(f.pus[0])
    for ward in f.wards:
        services.mark_dirty(**_args(f, ward))
    services.rebuild_contest(organization_id=f.org.id, contest_id=f.contest.id)
    with system_context():
        assert RollupDirty.objects.count() == 0


def test_drift_in_a_live_election_heals_itself(field_):
    f = field_
    f.submit(f.pus[0], (100, 40))
    f.submit(f.pus[3], (7, 9))
    assert services.self_heal_live_contests() == {"checked": 1, "repaired": 0}

    with system_context():
        Rollup.objects.filter(contest=f.contest, level="STATE").update(reported_valid=1)
        assert services.verify_contest(f.contest) != []
    assert services.self_heal_live_contests() == {"checked": 1, "repaired": 1}
    with system_context():
        assert services.verify_contest(f.contest) == []
        from apps.audit.models import AuditEvent

        assert AuditEvent.objects.filter(action="rollup.self_healed").count() == 1
