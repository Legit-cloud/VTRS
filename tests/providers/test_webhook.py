"""Twilio delivery receipts: the signature is the only gate (FR-6.12.4)."""

from urllib.parse import urlencode

import pytest
from django.db import transaction
from rest_framework.test import APIClient

from apps.core.rls import system_context
from apps.notifications import services
from apps.notifications.models import Delivery
from apps.notifications.providers import twilio_signature

from ..anomalies.helpers import deliveries

pytestmark = pytest.mark.django_db

PATH = "/api/v1/webhooks/twilio/status"
BASE = "https://vtrs.example.org"
TOKEN = "webhook-secret"


@pytest.fixture(autouse=True)
def _configured(settings):
    settings.VTRS_TWILIO_AUTH_TOKEN = TOKEN
    settings.VTRS_PUBLIC_BASE_URL = BASE


def _sent_sms(field):
    with transaction.atomic(), system_context():
        [note] = services.notify(
            organization_id=field.org.id,
            user_ids=[field.admin.user.id],
            kind="SYSTEM",
            title="t",
            body="b",
            channels=["SMS"],
        )
    services.deliver(field.org.id, [note.id])
    with system_context():
        delivery = Delivery.objects.get(notification=note, channel="SMS")
        message_id = delivery.provider_message_id
    return note, message_id


def _post(params, *, signature=None, url=BASE + PATH):
    client = APIClient()
    header = signature if signature is not None else twilio_signature(url, params, TOKEN)
    return client.generic(
        "POST",
        PATH,
        urlencode(params),
        content_type="application/x-www-form-urlencoded",
        HTTP_X_TWILIO_SIGNATURE=header,
    )


def test_a_delivered_receipt_updates_the_delivery(field_):
    note, message_id = _sent_sms(field_)
    response = _post({"MessageSid": message_id, "MessageStatus": "delivered", "To": "+23480"})
    assert response.status_code == 204
    assert deliveries(note)["SMS"] == "DELIVERED"


def test_a_failed_receipt_is_recorded_with_the_error_code(field_):
    note, message_id = _sent_sms(field_)
    _post({"MessageSid": message_id, "MessageStatus": "undelivered", "ErrorCode": "30003"})
    assert deliveries(note)["SMS"] == "FAILED"
    with system_context():
        assert Delivery.objects.get(notification=note, channel="SMS").detail == "30003"


def test_interim_statuses_change_nothing(field_):
    note, message_id = _sent_sms(field_)
    _post({"MessageSid": message_id, "MessageStatus": "queued"})
    assert deliveries(note)["SMS"] == "SENT"


def test_a_bad_signature_is_refused_and_changes_nothing(field_):
    note, message_id = _sent_sms(field_)
    params = {"MessageSid": message_id, "MessageStatus": "delivered"}
    assert _post(params, signature="not-the-signature").status_code == 403
    forged = twilio_signature(BASE + PATH, params, "some-other-token")
    assert _post(params, signature=forged).status_code == 403
    assert _post(params, signature="").status_code == 403
    assert deliveries(note)["SMS"] == "SENT"


def test_a_signature_for_other_parameters_does_not_verify(field_):
    _, message_id = _sent_sms(field_)
    signed = twilio_signature(
        BASE + PATH, {"MessageSid": message_id, "MessageStatus": "queued"}, TOKEN
    )
    response = _post({"MessageSid": message_id, "MessageStatus": "delivered"}, signature=signed)
    assert response.status_code == 403


def test_an_unknown_message_is_accepted_quietly(field_):
    response = _post({"MessageSid": "SMunknown", "MessageStatus": "delivered"})
    assert response.status_code == 204


def test_the_endpoint_is_closed_until_it_is_configured(settings):
    settings.VTRS_TWILIO_AUTH_TOKEN = ""
    assert (
        _post({"MessageSid": "x", "MessageStatus": "delivered"}, signature="x").status_code == 403
    )
