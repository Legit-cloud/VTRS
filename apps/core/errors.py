"""RFC 9457 problem+json errors with a stable machine `code` and the request id."""

import logging
from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.db import connections
from django.http import Http404
from rest_framework import exceptions
from rest_framework.response import Response

from .context import get_request_id

PROBLEM_CONTENT_TYPE = "application/problem+json"
logger = logging.getLogger("vtrs.errors")

_TITLES = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    406: "Not Acceptable",
    409: "Conflict",
    413: "Payload Too Large",
    415: "Unsupported Media Type",
    426: "Upgrade Required",
    429: "Too Many Requests",
    500: "Internal Server Error",
    503: "Service Unavailable",
}


class Forbidden(exceptions.APIException):
    status_code = 403
    default_detail = "You do not have permission to perform this action."
    default_code = "forbidden"


class MfaRequired(exceptions.APIException):
    status_code = 403
    default_detail = "This role requires multi-factor authentication. Enrol a second factor."
    default_code = "mfa_required"


class StepUpRequired(exceptions.APIException):
    status_code = 403
    default_detail = "Confirm your second factor again to perform this action."
    default_code = "mfa_step_up_required"


class IdempotencyConflict(exceptions.APIException):
    status_code = 409
    default_detail = "This Idempotency-Key was already used with a different request."
    default_code = "idempotency_conflict"


class InvalidIdempotencyKey(exceptions.APIException):
    status_code = 400
    default_detail = "An Idempotency-Key header of 1-128 characters [A-Za-z0-9_.:-] is required."
    default_code = "invalid_idempotency_key"


class UnknownQueryParameter(exceptions.APIException):
    status_code = 400
    default_detail = "Unknown query parameter."
    default_code = "unknown_query_parameter"


def _describe(exc: Exception) -> tuple[str, str, Any]:
    if isinstance(exc, exceptions.ValidationError):
        return "validation_error", "The request is invalid.", exc.detail
    if isinstance(exc, Http404):
        return "not_found", "Not found.", None
    if isinstance(exc, DjangoPermissionDenied):
        return "forbidden", Forbidden.default_detail, None
    if isinstance(exc, exceptions.APIException):
        detail = exc.detail
        if isinstance(detail, str):
            return str(exc.get_codes()), str(detail), None
        return exc.default_code, str(exc.default_detail), detail
    return "error", "Error.", None


def problem_response(status_code: int, code: str, detail: str, errors: Any = None) -> Response:
    body: dict[str, Any] = {
        "type": f"urn:vtrs:problem:{code}",
        "title": _TITLES.get(status_code, "Error"),
        "status": status_code,
        "detail": detail,
        "code": code,
        "request_id": get_request_id(),
    }
    if errors:
        body["errors"] = errors
    return Response(body, status=status_code, content_type=PROBLEM_CONTENT_TYPE)


class CommitsSideEffects:
    """Mixin for errors raised *after* deliberate writes that must survive the failed request.

    DRF rolls back the per-request transaction on every handled error. Failed sign-in counters,
    OTP attempt counts and refresh-token reuse revocations are exactly the writes that must
    not be undone, so exceptions carrying this mixin keep the transaction. They are only raised
    once the service's own savepoint has committed cleanly.
    """

    commits_side_effects = True


def _keep_request_transaction() -> None:
    for conn in connections.all(initialized_only=True):
        if conn.settings_dict.get("ATOMIC_REQUESTS") and conn.in_atomic_block:
            conn.set_rollback(False)


def problem_exception_handler(exc: Exception, context: dict[str, Any]) -> Response:
    # Imported lazily: this module is loaded while DRF's own settings are initialising.
    from rest_framework.views import exception_handler

    response = exception_handler(exc, context)
    if getattr(exc, "commits_side_effects", False):
        _keep_request_transaction()
    if response is None:
        logger.exception("unhandled_error", exc_info=exc)
        return problem_response(500, "server_error", "An unexpected error occurred.")
    code, detail, errors = _describe(exc)
    problem = problem_response(response.status_code, code, detail, errors)
    for header in ("Retry-After", "WWW-Authenticate", "Allow"):
        if header in response:
            problem[header] = response[header]
    return problem
