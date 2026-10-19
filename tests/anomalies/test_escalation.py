"""Alert routing and escalation (FR-6.9.7, FR-6.12.2, PB-10)."""

from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from apps.anomalies import routing
from apps.anomalies.models import AnomalyFlag, FlagEvent
from apps.core.domain.permissions import Role
from apps.core.rls import system_context
from apps.notifications.models import Notification
from apps.notifications.providers import FakeSmsProvider, FakeWhatsAppProvider

from .helpers import deliveries, flags_of, notifications_for, unit_with_coordinates, version_state

pytestmark = pytest.mark.django_db


@pytest.fixture
def chain(field_):
    """Ward officer, LGA officer and admin for ward A1, ready before anything is raised."""
    f = field_
    f.ward_officer = f.officer(Role.WARD_OFFICER, f.wards[0])
    f.lga_officer = f.officer(Role.LGA_OFFICER, f.lgas[0])
    f.pu = unit_with_coordinates(f)
    # A ward officer elsewhere must hear nothing.
    f.bystander = f.officer(Role.WARD_OFFICER, f.wards[3])
    return f


def _critical(f):
    """Over-voting: more accredited than registered voters. CRITICAL, from an inline rule."""
    accredited = (f.pu.registered_voters or 500) + 100
    return f.submit(
        f.pu,
        (120, 80),
        totals={"accredited": accredited, "rejected": 5, "total_cast": 205},
    )


def _medium(f):
    far_future = (timezone.now() + timedelta(hours=6)).isoformat()
    return f.submit(f.pu, device_captured_at=far_future)


def _escalate(f):
    """Run the sweep and its after-commit deliveries, as a worker would."""
    with f.capture(execute=True):
        return routing.escalate_overdue()


def _flag(version_id, rule):
    return next(x for x in flags_of(version_id) if x.rule_code == rule)


def _kinds(user):
    return [n.kind for n in notifications_for(user.user.id)]


def test_a_critical_flag_tells_the_whole_chain_on_every_channel(chain):
    f = chain
    outcome = _critical(f)
    flag = _flag(outcome["version_id"], "OVER_VOTING")
    assert flag.severity == "CRITICAL"
    assert flag.notified_at is not None
    assert flag.escalation_level == 2  # admin rung: everyone was told at once
    due_in = flag.sla_due_at - timezone.now()
    assert timedelta(minutes=14) < due_in <= timedelta(minutes=15)

    for member in (f.ward_officer, f.lga_officer, f.admin):
        [note] = [
            n for n in notifications_for(member.user.id) if n.data.get("flag_id") == str(flag.id)
        ]
        assert note.kind == "ANOMALY"
        assert note.severity == "CRITICAL"
        assert "Open the flag" in note.body
        assert deliveries(note) == {"IN_APP": "DELIVERED", "SMS": "SENT", "EMAIL": "SENT"}
    assert notifications_for(f.bystander.user.id) == []
    sent_to = {m.to for m in FakeSmsProvider.outbox}
    assert {f.ward_officer.phone, f.lga_officer.phone, f.admin.phone} <= sent_to
    assert len(mail.outbox) >= 3


def test_a_medium_flag_goes_to_the_ward_officer_first(chain):
    f = chain
    outcome = _medium(f)
    flag = _flag(outcome["version_id"], "DEVICE_CLOCK_AHEAD")
    assert flag.escalation_level == 0
    assert _kinds(f.ward_officer) == ["ANOMALY"]
    assert _kinds(f.lga_officer) == []
    assert _kinds(f.admin) == []
    note = notifications_for(f.ward_officer.user.id)[0]
    assert deliveries(note) == {"IN_APP": "DELIVERED"}  # in-app only at this severity


def test_an_unacknowledged_flag_climbs_the_chain(chain):
    f = chain
    outcome = _medium(f)
    flag = _flag(outcome["version_id"], "DEVICE_CLOCK_AHEAD")

    def overdue():
        with system_context():
            AnomalyFlag.objects.filter(id=flag.id).update(
                sla_due_at=timezone.now() - timedelta(minutes=1)
            )

    overdue()
    assert _escalate(f) == 1
    with system_context():
        flag.refresh_from_db()
    assert flag.escalation_level == 1  # the LGA officer is next
    assert flag.sla_due_at is not None
    assert _kinds(f.lga_officer) == ["ANOMALY_ESCALATED"]
    escalated = notifications_for(f.lga_officer.user.id)[0]
    assert escalated.title.startswith("ESCALATED")
    assert deliveries(escalated) == {"IN_APP": "DELIVERED", "EMAIL": "SENT"}
    assert _kinds(f.admin) == []

    overdue()
    assert _escalate(f) == 1
    with system_context():
        flag.refresh_from_db()
    assert flag.escalation_level == 2
    assert flag.sla_due_at is None  # nobody above the admin
    assert _kinds(f.admin) == ["ANOMALY_ESCALATED"]
    with system_context():
        events = list(FlagEvent.objects.filter(flag=flag, action="ESCALATED"))
    assert [e.details["to_level"] for e in events] == [1, 2]


def test_an_acknowledged_flag_does_not_escalate(chain):
    f = chain
    outcome = _medium(f)
    flag = _flag(outcome["version_id"], "DEVICE_CLOCK_AHEAD")
    ack = f.client_as(f.ward_officer).post(
        f"/api/v1/flags/{flag.id}/acknowledge", {}, format="json", HTTP_IDEMPOTENCY_KEY="ack-1"
    )
    assert ack.status_code == 200
    with system_context():
        AnomalyFlag.objects.filter(id=flag.id).update(
            sla_due_at=timezone.now() - timedelta(minutes=5)
        )
    assert _escalate(f) == 0
    assert _kinds(f.lga_officer) == []


def test_a_critical_flag_nobody_answers_is_paged_again_once(chain, settings):
    f = chain
    settings.VTRS_FEATURE_WHATSAPP_ALERTS = True
    outcome = _critical(f)
    flag = _flag(outcome["version_id"], "OVER_VOTING")
    with system_context():
        AnomalyFlag.objects.filter(id=flag.id).update(
            sla_due_at=timezone.now() - timedelta(minutes=1)
        )
    assert _escalate(f) == 1  # already at the top rung: a louder reminder
    admin_notes = notifications_for(f.admin.user.id)
    assert [n.kind for n in admin_notes] == ["ANOMALY", "ANOMALY_ESCALATED"]
    assert deliveries(admin_notes[1])["WHATSAPP"] == "SENT"
    assert {m.to for m in FakeWhatsAppProvider.outbox} == {f.admin.phone}
    assert _escalate(f) == 0  # the clock is stopped


def test_information_only_flags_stay_quiet(chain):
    f = chain
    gps = {"lat": float(f.pu.latitude), "lng": float(f.pu.longitude), "accuracy_m": 450}
    outcome = f.submit(f.pu, gps=gps)
    flag = _flag(outcome["version_id"], "GPS_LOW_ACCURACY")
    assert flag.severity == "INFO"
    assert flag.sla_due_at is None
    assert notifications_for(f.ward_officer.user.id) == []
    assert version_state(outcome["version_id"]) == "SUBMITTED"


def test_routing_is_idempotent(chain):
    f = chain
    outcome = _critical(f)
    flag = _flag(outcome["version_id"], "OVER_VOTING")
    with system_context():
        before = Notification.objects.count()
    assert routing.route_flags(f.org.id, [flag.id]) == 0  # notified_at already set
    with system_context():
        assert Notification.objects.count() == before


def test_the_matrix_can_be_retuned_without_code(chain, settings):
    f = chain
    settings.VTRS_ESCALATION_MATRIX = {
        "MEDIUM": {"notify": ["WARD", "LGA"], "channels": ["IN_APP", "EMAIL"], "ack_minutes": 5}
    }
    outcome = _medium(f)
    flag = _flag(outcome["version_id"], "DEVICE_CLOCK_AHEAD")
    assert flag.escalation_level == 1
    assert (flag.sla_due_at - timezone.now()) < timedelta(minutes=5)
    assert _kinds(f.lga_officer) == ["ANOMALY"]


def test_an_organization_with_nobody_in_scope_does_not_break(field_):
    f = field_  # no officers created; only the admin exists
    pu = unit_with_coordinates(f)
    outcome = f.submit(pu, gps=None)  # GPS_MISSING, MEDIUM: ward level, nobody there
    flag = _flag(outcome["version_id"], "GPS_MISSING")
    assert flag.notified_at is not None
    assert notifications_for(f.admin.user.id) == []
