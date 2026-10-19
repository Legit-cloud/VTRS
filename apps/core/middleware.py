import re
from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils.cache import patch_vary_headers

from .context import client_ip_var, get_request_id, request_id_var
from .ids import uuid7

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")


class RequestContextMiddleware:
    """Assigns a request id (or accepts a well-formed one from the edge) and records the client IP.

    REMOTE_ADDR is used as-is; trusted-proxy handling belongs with the edge configuration.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else str(uuid7())
        rid_token = request_id_var.set(request_id)
        ip_token = client_ip_var.set(request.META.get("REMOTE_ADDR") or None)
        try:
            response = self.get_response(request)
        finally:
            request_id_var.reset(rid_token)
            client_ip_var.reset(ip_token)
        response[REQUEST_ID_HEADER] = request_id
        return response


class ApiBoundaryMiddleware:
    """Cross-origin access for the web portal, and hardening of every API response.

    CORS is an allowlist of exact origins (`VTRS_CORS_ALLOWED_ORIGINS`), never a wildcard, and
    carries no credentials: the portal sends a bearer token, not cookies. API responses are
    never cached by browsers or proxies (they hold results, tokens and download links), and
    carry a CSP that forbids rendering them as a page.
    """

    ALLOW_METHODS = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    ALLOW_HEADERS = (
        "Authorization, Content-Type, Idempotency-Key, If-Match, "
        "X-Request-ID, X-App-Platform, X-App-Version"
    )
    EXPOSE_HEADERS = "ETag, Idempotent-Replayed, Retry-After, X-Request-ID"

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        origin = request.headers.get("Origin", "")
        allowed = bool(origin) and origin in settings.VTRS_CORS_ALLOWED_ORIGINS
        is_preflight = (
            request.method == "OPTIONS" and "Access-Control-Request-Method" in request.headers
        )
        if is_preflight:
            response = HttpResponse(status=204)
            if allowed:
                response["Access-Control-Allow-Origin"] = origin
                response["Access-Control-Allow-Methods"] = self.ALLOW_METHODS
                response["Access-Control-Allow-Headers"] = self.ALLOW_HEADERS
                response["Access-Control-Max-Age"] = "600"
            patch_vary_headers(response, ["Origin"])
            return response
        if request.path.startswith("/api/") and any(
            "\x00" in key or "\x00" in value
            for key, values in request.GET.lists()
            for value in [key, *values]
        ):
            # PostgreSQL text cannot hold NUL; refuse it here, for every endpoint.
            return JsonResponse(
                {
                    "type": "urn:vtrs:problem:bad_request",
                    "title": "Bad Request",
                    "status": 400,
                    "detail": "Query parameters cannot contain NUL characters.",
                    "code": "bad_request",
                    "request_id": get_request_id(),
                },
                status=400,
                content_type="application/problem+json",
            )
        response = self.get_response(request)
        if allowed:
            response["Access-Control-Allow-Origin"] = origin
            response["Access-Control-Expose-Headers"] = self.EXPOSE_HEADERS
        if origin:
            patch_vary_headers(response, ["Origin"])
        if request.path.startswith("/api/"):
            response.setdefault("Cache-Control", "no-store")
            response.setdefault(
                "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
            )
            response.setdefault("X-Content-Type-Options", "nosniff")
        return response
