"""AC-13 / SEC-06: audit rows are append-only, sealed into a hash chain, and tampering shows."""

from unittest import mock

import pytest
from django.db import DatabaseError, connection, transaction

from apps.audit import services
from apps.audit.models import AuditBatch, AuditEvent
from apps.core.context import request_id_var
from apps.core.domain.permissions import Role

pytestmark = pytest.mark.django_db


def _record(n=1, **kwargs):
    return [
        services.record(action="test.action", object_type="thing", object_id=i, **kwargs)
        for i in range(n)
    ]


def test_record_captures_actor_and_request_context(make_actor):
    actor = make_actor(Role.LGA_OFFICER)
    token = request_id_var.set("rid-test-0001")
    try:
        (event,) = _record(actor=actor, diff={"before": None, "after": {"x": 1}})
    finally:
        request_id_var.reset(token)
    stored = AuditEvent.objects.get(id=event.id)
    assert stored.actor_id == actor.user_id
    assert stored.actor_role == "LGA_OFFICER"
    assert stored.organization_id == actor.organization_id
    assert stored.request_id == "rid-test-0001"
    assert stored.diff == {"before": None, "after": {"x": 1}}


def test_record_refuses_to_run_outside_a_transaction():
    with mock.patch.object(transaction, "get_connection") as get_connection:
        get_connection.return_value.in_atomic_block = False
        with pytest.raises(RuntimeError):
            _record()


def _expect_db_rejection(statement, params):
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(statement, params)


def test_events_cannot_be_updated_or_deleted():
    (event,) = _record()
    _expect_db_rejection("UPDATE audit_event SET action = 'x' WHERE id = %s", [event.id])
    _expect_db_rejection("DELETE FROM audit_event WHERE id = %s", [event.id])
    assert AuditEvent.objects.get(id=event.id).action == "test.action"


def test_batch_id_can_be_set_once_only():
    (event,) = _record()
    batch = services.seal_pending(lag_seconds=0)
    assert AuditEvent.objects.get(id=event.id).batch_id == batch.id
    _expect_db_rejection("UPDATE audit_event SET batch_id = NULL WHERE id = %s", [event.id])


def test_batches_cannot_be_rewritten():
    _record()
    batch = services.seal_pending(lag_seconds=0)
    _expect_db_rejection("UPDATE audit_batch SET root = 'x' WHERE id = %s", [batch.id])
    _expect_db_rejection("DELETE FROM audit_batch WHERE id = %s", [batch.id])


def test_sealing_chains_batches_and_verifies():
    _record(3)
    first = services.seal_pending(lag_seconds=0)
    assert services.seal_pending(lag_seconds=0) is None  # nothing new
    _record(2)
    second = services.seal_pending(lag_seconds=0)
    assert (first.seq, first.event_count) == (1, 3)
    assert (second.seq, second.event_count) == (2, 2)
    assert second.prev_root == first.root
    assert services.verify_chain() == []


def test_sealer_respects_the_lag_window():
    _record()
    assert services.seal_pending(lag_seconds=3600) is None


def _bypass_triggers():
    # Simulates an insider with superuser access: drop to the superuser, then disable triggers.
    with connection.cursor() as cursor:
        cursor.execute("RESET ROLE")
        cursor.execute("SET LOCAL session_replication_role = replica")


def test_verifier_detects_an_edited_event():
    events = _record(4)
    services.seal_pending(lag_seconds=0)
    _bypass_triggers()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE audit_event SET diff = '{\"forged\": true}' WHERE id = %s", [events[2].id]
        )
    problems = services.verify_chain()
    assert any("Merkle root mismatch" in p for p in problems)


def test_verifier_detects_a_deleted_event():
    events = _record(4)
    services.seal_pending(lag_seconds=0)
    _bypass_triggers()
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM audit_event WHERE id = %s", [events[0].id])
    problems = services.verify_chain()
    assert any("holds 3 events, sealed 4" in p for p in problems)


def test_verifier_detects_a_rewritten_batch():
    _record(2)
    services.seal_pending(lag_seconds=0)
    _record(2)
    services.seal_pending(lag_seconds=0)
    _bypass_triggers()
    with connection.cursor() as cursor:
        cursor.execute("UPDATE audit_batch SET root = %s WHERE seq = 1", ["f" * 64])
    problems = services.verify_chain()
    assert any("batch 1: chained root mismatch" in p for p in problems)
    assert any("batch 2: does not chain" in p for p in problems)


def test_partitions_can_be_extended():
    services.ensure_partitions(months_ahead=6)
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM pg_inherits WHERE inhparent = 'audit_event'::regclass")
        (partitions,) = cursor.fetchone()
    assert partitions >= 7  # six months ahead plus the current one (and the default)
    assert AuditBatch.objects.count() == 0
