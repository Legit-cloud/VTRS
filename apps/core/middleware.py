import re
from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse

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


def _version_tuple(value: str) -> tuple[int, ...] | None:
    try:
        return tuple(int(part) for part in value.strip().split("."))
    except ValueError:
        return None


class MinimumAppVersionMiddleware:
    """Mobile clients below the supported version get 426 (spec section 9).

    The app sends X-App-Platform (android/ios) and X-App-Version (dotted numbers). Web clients
    and server-side callers send neither and are unaffected.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        platform = request.headers.get("X-App-Platform", "").lower()
        if platform in {"android", "ios"}:
            minimum = _version_tuple(settings.VTRS_MIN_APP_VERSION)
            reported = _version_tuple(request.headers.get("X-App-Version", ""))
            if minimum and (reported is None or reported < minimum):
                return JsonResponse(
                    {
                        "type": "urn:vtrs:problem:upgrade_required",
                        "title": "Upgrade Required",
                        "status": 426,
                        "detail": f"Update the app to version {settings.VTRS_MIN_APP_VERSION}.",
                        "code": "upgrade_required",
                        "request_id": get_request_id(),
                    },
                    status=426,
                    content_type="application/problem+json",
                )
        return self.get_response(request)
