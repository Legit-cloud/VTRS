"""Workers recomputing different wards at the same moment must not lose each other's figures.

Real connections and real commits. Each round zeroes every rollup, then four workers (two per
LGA) recompute their wards at once. Without the per-contest lock, an LGA row can be summed from
a ward row the other worker has not committed yet, and the state ends up short.
"""

import threading

import pytest
from django.db import connection, transaction
from django.utils import timezone

from apps.accounts.models import User, UserStatus
from apps.aggregation import services
from apps.aggregation.models import Rollup, RollupDirty, RollupVote
from apps.core.crypto import blind_index
from apps.core.ids import uuid7
from apps.elections.models import Election
from apps.geography.models import PollingUnit, State, Ward
from apps.organizations.models import Organization
from apps.results.models import PuResult, ResultVersion, VoteLine

from ..factories import election_type, load_reference_data, make_ballot

ROUNDS = 12


def _seed():
    with transaction.atomic():
        load_reference_data(lgas=2, wards=4, polling_units=8, seed=5)
    org = Organization.objects.create(name="Lock Party", status="ACTIVE")
    email = "admin@lock.example"
    user = User.objects.create_user(
        password="x" * 20,
        email=email,
        email_index=blind_index("email", email),
        status=UserStatus.ACTIVE,
    )
    election = Election.objects.create(
        organization=org,
        name="Lock",
        election_type=election_type(),
        state=State.objects.get(),
        election_date="2027-03-11",
        status="LIVE",
        created_by_id=user.id,
    )
    ballot = make_ballot(org, election, ("P1", "P2"), own=None)
    contest, candidates = ballot.contest, ballot.candidates
    for index, pu in enumerate(PollingUnit.objects.order_by("inec_code")):
        pu_result = PuResult.objects.create(
            organization=org,
            election=election,
            contest=contest,
            polling_unit=pu,
            ward=pu.ward,
            lga=pu.lga,
            state=pu.state,
            status="SUBMITTED",
            version_count=1,
        )
        version = ResultVersion.objects.create(
            id=uuid7(),
            organization=org,
            pu_result=pu_result,
            contest=contest,
            polling_unit=pu,
            ward=pu.ward,
            lga=pu.lga,
            version_no=1,
            valid=15 + 2 * index,
            device_captured_at=timezone.now(),
            server_received_at=timezone.now(),
            submitted_by=user,
            config_version=1,
            payload_hash="0" * 64,
            state="SUBMITTED",
        )
        for candidate, votes in zip(candidates, (10 + index, 5 + index), strict=True):
            VoteLine.objects.create(
                organization=org, result_version=version, candidate=candidate, votes=votes
            )
        PuResult.objects.filter(id=pu_result.id).update(head_version=version)
    return org, contest


@pytest.mark.django_db(transaction=True)
def test_concurrent_recomputes_converge():
    org, contest = _seed()
    services.rebuild_contest(organization_id=org.id, contest_id=contest.id)
    with transaction.atomic():
        assert services.verify_contest(contest) == []

    wards = list(Ward.objects.order_by("inec_code"))
    failures: list[str] = []
    for round_no in range(ROUNDS):
        Rollup.objects.filter(contest=contest).update(reported_pus=0, reported_valid=0)
        RollupVote.objects.filter(rollup__contest=contest).update(reported_votes=0)

        barrier = threading.Barrier(len(wards))
        errors: list[BaseException] = []

        def work(ward, barrier=barrier, errors=errors):
            try:
                barrier.wait()
                services.recompute_ward(
                    organization_id=org.id, contest_id=contest.id, ward_id=ward.id
                )
            except BaseException as exc:  # reported through the list below
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=work, args=(ward,)) for ward in wards]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert not errors, errors

        with transaction.atomic():
            problems = services.verify_contest(contest)
        if problems:
            failures.append(f"round {round_no}: {problems[:3]}")
    assert not failures, failures


@pytest.mark.django_db(transaction=True)
def test_a_busy_contest_is_not_waited_on_and_its_marks_are_kept():
    org, contest = _seed()
    services.rebuild_contest(organization_id=org.id, contest_id=contest.id)
    ward = Ward.objects.order_by("inec_code").first()
    held, release = threading.Event(), threading.Event()

    def holder():
        try:
            with transaction.atomic():
                services._lock_contest(contest.id)
                held.set()
                release.wait(timeout=15)
        finally:
            connection.close()

    thread = threading.Thread(target=holder)
    thread.start()
    assert held.wait(timeout=10)
    try:
        services.mark_dirty(organization_id=org.id, contest_id=contest.id, ward_id=ward.id)
        busy = services.drain_contest(organization_id=org.id, contest_id=contest.id, wait=False)
        assert busy == {"busy": True}
        with transaction.atomic():
            assert RollupDirty.objects.count() == 1  # still there for whoever drains next
    finally:
        release.set()
        thread.join()
    done = services.drain_contest(organization_id=org.id, contest_id=contest.id, wait=False)
    assert done["wards_refreshed"] == 1
    with transaction.atomic():
        assert RollupDirty.objects.count() == 0
