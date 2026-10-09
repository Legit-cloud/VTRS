"""Request context, problem+json errors, logging scrubbing and the per-view policy rule."""

import json
import logging

import pytest
from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.views import APIView

from apps.core.logging import JsonFormatter, mask_text, scrub

pytestmark = pytest.mark.django_db


def _walk(patterns):
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            yield from _walk(pattern.url_patterns)
        elif isinstance(pattern, URLPattern):
            yield pattern


def test_every_api_view_declares_a_policy():
    """Spec section 8: a view without `required_permission` or `public = True` fails CI."""
    views = []
    for pattern in _walk(get_resolver().url_patterns):
        view = getattr(pattern.callback, "cls", None) or getattr(
            pattern.callback, "view_class", None
        )
        if view is not None and issubclass(view, APIView):
            views.append(view)
            declared = getattr(view, "public", False) is True or bool(
                getattr(view, "required_permission", None)
            )
            assert declared, f"{view.__module__}.{view.__name__} declares no access policy"
    assert views


def test_request_id_is_generated_and_echoed(api_client):
    response = api_client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert len(response["X-Request-ID"]) >= 8

    response = api_client.get("/api/v1/health/live", HTTP_X_REQUEST_ID="edge-abc-12345")
    assert response["X-Request-ID"] == "edge-abc-12345"

    response = api_client.get("/api/v1/health/live", HTTP_X_REQUEST_ID="bad id; drop table")
    assert response["X-Request-ID"] != "bad id; drop table"


def test_health_and_time_are_public(api_client):
    assert api_client.get("/api/v1/health/ready").json() == {"status": "ready"}
    assert "now" in api_client.get("/api/v1/time").json()


def test_unauthenticated_request_gets_problem_json(api_client):
    response = api_client.get("/api/v1/geography/lgas")
    assert response.status_code == 401
    assert response["Content-Type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "not_authenticated"
    assert body["status"] == 401
    assert body["request_id"] == response["X-Request-ID"]
    assert "WWW-Authenticate" in response


def test_log_scrubbing():
    assert mask_text("call 08031234567 now") == "call ********567 now"
    assert mask_text("Authorization: Bearer abc.def.ghi") == "Authorization: Bearer [redacted]"
    assert scrub({"password": "x", "otp_code": "123456", "nested": [{"refresh_token": "t"}]}) == {
        "password": "[redacted]",
        "otp_code": "[redacted]",
        "nested": [{"refresh_token": "[redacted]"}],
    }


def test_json_formatter_scrubs_extras():
    record = logging.LogRecord(
        "vtrs", logging.INFO, __file__, 1, "sent to +2348031234567", (), None
    )
    record.phone = "+2348031234567"
    record.request_id = "rid-12345678"
    line = json.loads(JsonFormatter().format(record))
    assert line["msg"] == "sent to ***********567"
    assert line["extra"] == {"phone": "[redacted]"}
    assert line["request_id"] == "rid-12345678"
