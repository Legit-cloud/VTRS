"""Optimistic concurrency for admin configuration edits: ETag on read, If-Match on update.

Two admins editing the same contest cannot silently overwrite each other (spec section 9).
"""

from rest_framework.exceptions import APIException
from rest_framework.request import Request
from rest_framework.response import Response


class PreconditionRequired(APIException):
    status_code = 428
    default_detail = "Send If-Match with the ETag from your last read."
    default_code = "precondition_required"


class PreconditionFailed(APIException):
    status_code = 412
    default_detail = "This was changed since you last read it. Reload and try again."
    default_code = "precondition_failed"


def etag(version: int) -> str:
    return f'"{version}"'


def with_etag(response: Response, version: int) -> Response:
    response["ETag"] = etag(version)
    return response


def if_match_version(request: Request) -> int:
    header = request.headers.get("If-Match", "").strip()
    if not header:
        raise PreconditionRequired()
    value = header.removeprefix("W/").strip('"')
    try:
        return int(value)
    except ValueError:
        raise PreconditionFailed() from None


def check_version(expected: int, current: int) -> None:
    if expected != current:
        raise PreconditionFailed()
