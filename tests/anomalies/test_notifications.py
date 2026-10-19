"""Notifications and delivery tracking (FR-6.12.1, FR-6.12.2, FR-6.12.4)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.core.domain.permissions import Role
from apps.core.ids import uuid7
from apps.core.rls import system_context
from apps.notifications import services
from apps.notifications.models import Delivery, Notification
from apps.notifications.providers import FakeSmsProvider

from .helpers import deliveries, notifications_for

pytestmark = pytest.mark.django_db


def _notify(f, member, *, channels=("SMS",), title="Check this", **kwargs):
    from django.db import transaction

    with transaction.atomic(), system_context():
        created = services.notify(
            organization_id=f.org.id,
            user_ids=[member.user.id],
            kind="SYSTEM",
            title=title,
            body="Something needs you.",
            data={"k": "v"},
            channels=channels,
            **kwargs,
        )
    return created[0]


def _commit(f, fn):
    with f.capture(execute=True):
        return fn()


def _reject(f, outcome, reason="Totals do not match the photo"):
    return f.admin_client().post(
        f"/api/v1/results/{outcome['version_id']}/review",
        {"decision": "REJECTED", "reason": reason},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid7()),
    )


def test_a_rejected_result_reaches_the_agents_inbox(reviewed_field):
    """The agent sees the reason in the web app (inbox and their polling unit's status)."""
    f = reviewed_field
    pu = f.pus[0]
    agent = f.agents[pu.id]
    outcome = f.submit(pu, (100, 50))
    assert _reject(f, outcome).status_code == 200

    [note] = notifications_for(agent.member.user.id, kind="RESULT_REJECTED")
    assert "Result rejected" in note.title
    assert "Totals do not match the photo" in note.body
    assert note.data["version_id"] == outcome["version_id"]
    assert deliveries(note) == {"IN_APP": "DELIVERED"}
    inbox = agent.client.get("/api/v1/me/notifications").json()["results"]
    assert inbox[0]["title"] == note.title
    status = agent.client.get(f"/api/v1/submissions/{outcome['version_id']}").json()
    assert status["review"]["reason"] == "Totals do not match the photo"


def test_an_approval_is_an_inbox_entry_only(reviewed_field):
    f = reviewed_field
    pu = f.pus[0]
    outcome = f.submit(pu, (100, 50))
    assert f.verify(outcome).status_code == 200
    [note] = notifications_for(f.agents[pu.id].member.user.id, kind="RESULT_APPROVED")
    assert deliveries(note) == {"IN_APP": "DELIVERED"}


def test_a_failed_send_is_retried_then_given_up_on(field_, monkeypatch):
    f = field_
    calls = {"n": 0}

    def broken(self, to, body):
        calls["n"] += 1
        raise ConnectionError("provider down")

    monkeypatch.setattr(FakeSmsProvider, "send", broken)
    note = _commit(f, lambda: _notify(f, f.admin))
    assert deliveries(note)["SMS"] == "FAILED"
    with system_context():
        d = Delivery.objects.get(notification=note, channel="SMS")
        assert (d.attempts, d.detail) == (1, "ConnectionError")

    for expected_attempts in (2, 3):
        with system_context():
            Delivery.objects.filter(id=d.id).update(
                last_attempt_at=timezone.now() - timedelta(minutes=5)
            )
        services.retry_failed()
        with system_context():
            assert Delivery.objects.get(id=d.id).attempts == expected_attempts
    with system_context():
        Delivery.objects.filter(id=d.id).update(
            last_attempt_at=timezone.now() - timedelta(minutes=5)
        )
    assert services.retry_failed() == 0  # three attempts is the limit
    assert calls["n"] == 3


def test_a_retry_that_works_marks_the_delivery_sent(field_, monkeypatch):
    f = field_
    original = FakeSmsProvider.send
    state = {"down": True}

    def flaky(self, to, body):
        if state["down"]:
            raise TimeoutError("slow")
        return original(self, to, body)

    monkeypatch.setattr(FakeSmsProvider, "send", flaky)
    note = _commit(f, lambda: _notify(f, f.admin))
    assert deliveries(note)["SMS"] == "FAILED"
    state["down"] = False
    with system_context():
        Delivery.objects.filter(notification=note, channel="SMS").update(
            last_attempt_at=timezone.now() - timedelta(minutes=5)
        )
    assert services.retry_failed() == 1
    assert deliveries(note)["SMS"] == "SENT"


def test_redelivery_never_sends_twice(field_):
    f = field_
    note = _commit(f, lambda: _notify(f, f.admin))
    assert len(FakeSmsProvider.outbox) == 1
    assert services.deliver(f.org.id, [note.id]) == 0
    assert len(FakeSmsProvider.outbox) == 1


def test_receipts_move_a_delivery_to_delivered(field_):
    f = field_
    note = _commit(f, lambda: _notify(f, f.admin))
    with system_context():
        message_id = Delivery.objects.get(notification=note, channel="SMS").provider_message_id
    assert message_id
    assert services.record_receipt(channel="SMS", provider_message_id=message_id, delivered=True)
    assert deliveries(note)["SMS"] == "DELIVERED"
    assert not services.record_receipt(channel="SMS", provider_message_id="nope", delivered=True)


def test_a_user_without_a_phone_is_skipped(field_):
    f = field_
    with system_context():
        user = User.objects.get(id=f.admin.user.id)
        user.phone = ""
        user.save(update_fields=["phone"])
    note = _commit(f, lambda: _notify(f, f.admin))
    assert deliveries(note)["SMS"] == "SKIPPED"


def test_whatsapp_is_off_until_the_feature_is_enabled(field_, settings):
    f = field_
    note = _commit(f, lambda: _notify(f, f.admin, channels=("WHATSAPP",)))
    assert deliveries(note)["WHATSAPP"] == "SKIPPED"
    settings.VTRS_FEATURE_WHATSAPP_ALERTS = True
    second = _commit(f, lambda: _notify(f, f.admin, channels=("WHATSAPP",), title="Again"))
    assert deliveries(second)["WHATSAPP"] == "SENT"


def test_the_inbox_is_private_and_trackable(field_):
    f = field_
    mine = _commit(f, lambda: _notify(f, f.admin, channels=("SMS", "EMAIL")))
    other = f.officer(Role.WARD_OFFICER, f.wards[0])
    _commit(f, lambda: _notify(f, other, title="Not yours"))
    client = f.admin_client()

    listing = client.get("/api/v1/me/notifications").json()["results"]
    assert [n["title"] for n in listing] == ["Check this"]
    assert {d["channel"]: d["status"] for d in listing[0]["deliveries"]} == {
        "IN_APP": "DELIVERED",
        "SMS": "SENT",
        "EMAIL": "SENT",
    }
    assert listing[0]["link"] == {"k": "v"}
    assert client.get("/api/v1/me/notifications/unread-count").json() == {"unread": 1}

    stranger = f.client_as(other)
    assert stranger.post(f"/api/v1/me/notifications/{mine.id}/read").status_code == 404

    read = client.post(f"/api/v1/me/notifications/{mine.id}/read")
    assert read.status_code == 200 and read.json()["read_at"] is not None
    assert client.get("/api/v1/me/notifications/unread-count").json() == {"unread": 0}
    assert client.get("/api/v1/me/notifications", {"unread": "true"}).json()["results"] == []
    assert client.get("/api/v1/me/notifications", {"unread": "maybe"}).status_code == 400


def test_mark_all_read(field_):
    f = field_
    for n in range(3):
        _commit(f, lambda n=n: _notify(f, f.admin, channels=(), title=f"Note {n}"))
    client = f.admin_client()
    assert client.get("/api/v1/me/notifications/unread-count").json() == {"unread": 3}
    assert client.post("/api/v1/me/notifications/read-all").json() == {"marked": 3}
    assert client.get("/api/v1/me/notifications/unread-count").json() == {"unread": 0}
    with system_context():
        assert Notification.objects.filter(read_at__isnull=True).count() == 0
