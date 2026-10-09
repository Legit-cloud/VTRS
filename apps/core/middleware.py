import re
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from .context import client_ip_var, request_id_var
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
