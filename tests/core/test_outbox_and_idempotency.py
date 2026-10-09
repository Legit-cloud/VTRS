from datetime import timedelta
from unittest import mock

import pytest
from django.db import transaction
from django.utils import timezone

from apps.core import services
from apps.core.errors import IdempotencyConflict, InvalidIdempotencyKey
from apps.core.ids import uuid7
from apps.core.models import IdempotencyRecord, OutboxEvent

pytestmark = pytest.mark.django_db

ROUTES = {"result.accepted": ("apps.fake.handle", "ingest")}


def test_emit_requires_a_transaction():
    with mock.patch.object(transaction, "get_connection") as get_connection:
        get_connection.return_value.in_atomic_block = False
        with pytest.raises(RuntimeError):
            services.emit("x", {})


def test_emit_dispatches_after_commit(settings, django_capture_on_commit_callbacks):
    settings.VTRS_OUTBOX_ROUTES = ROUTES
    with mock.patch("apps.core.services.current_app.send_task") as send_task:
        with django_capture_on_commit_callbacks(execute=True):
            event = services.emit("result.accepted", {"version_id": uuid7()})
            assert not send_task.called  # nothing leaves before commit
    send_task.assert_called_once()
    assert send_task.call_args.kwargs["queue"] == "ingest"
    event.refresh_from_db()
    assert event.published_at is not None


def test_failed_fast_path_is_left_for_the_relay(settings, django_capture_on_commit_callbacks):
    settings.VTRS_OUTBOX_ROUTES = ROUTES
    with mock.patch("apps.core.services.current_app.send_task", side_effect=ConnectionError):
        with django_capture_on_commit_callbacks(execute=True):
            event = services.emit("result.accepted", {})
    event.refresh_from_db()
    assert event.published_at is None

    with mock.patch("apps.core.services.current_app.send_task") as send_task:
        assert services.relay_pending(min_age_seconds=0) == 1
    send_task.assert_called_once()
    event.refresh_from_db()
    assert event.published_at is not None
    assert services.relay_pending(min_age_seconds=0) == 0


def test_relay_skips_events_inside_the_fast_path_window(settings):
    settings.VTRS_OUTBOX_ROUTES = ROUTES
    OutboxEvent.objects.create(topic="result.accepted")
    with mock.patch("apps.core.services.current_app.send_task") as send_task:
        assert services.relay_pending(min_age_seconds=60) == 0
    send_task.assert_not_called()


def test_purge_removes_expired_records():
    old = timezone.now() - timedelta(days=30)
    OutboxEvent.objects.create(topic="t", published_at=old)
    OutboxEvent.objects.create(topic="t")  # unpublished: kept
    IdempotencyRecord.objects.create(
        user_id=uuid7(), scope="s", key="k", request_hash="h", expires_at=old
    )
    assert services.purge_expired() == {"idempotency_records": 1, "outbox_events": 1}
    assert OutboxEvent.objects.count() == 1


def _run(key, request_hash, user_id, calls):
    def operation():
        calls.append(1)
        return 201, {"id": uuid7()}

    return services.run_idempotent(
        user_id=user_id,
        scope="sync.submit",
        key=key,
        request_hash=request_hash,
        operation=operation,
    )


def test_idempotent_replay_returns_the_stored_response():
    user, calls = uuid7(), []
    first = _run("abc-123", "h1", user, calls)
    second = _run("abc-123", "h1", user, calls)
    assert len(calls) == 1
    assert (first.replayed, second.replayed) == (False, True)
    assert second.status == 201
    assert second.body == first.body


def test_same_key_different_payload_conflicts():
    user = uuid7()
    _run("abc-123", "h1", user, [])
    with pytest.raises(IdempotencyConflict):
        _run("abc-123", "h2", user, [])


def test_keys_are_per_user():
    calls = []
    _run("abc-123", "h1", uuid7(), calls)
    _run("abc-123", "h1", uuid7(), calls)
    assert len(calls) == 2


def test_failed_operation_leaves_the_key_reusable():
    user = uuid7()

    def boom():
        raise ValueError("boom")

    with pytest.raises(ValueError):
        services.run_idempotent(user_id=user, scope="s", key="k1", request_hash="h", operation=boom)
    assert not IdempotencyRecord.objects.filter(key="k1").exists()


@pytest.mark.parametrize("key", ["", "has space", "x" * 129, "semi;colon"])
def test_malformed_keys_are_rejected(key):
    with pytest.raises(InvalidIdempotencyKey):
        _run(key, "h", uuid7(), [])
