from collections.abc import Callable
from typing import Any

from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.domain.canonical import payload_hash
from apps.core.errors import InvalidIdempotencyKey
from apps.core.services import run_idempotent

IDEMPOTENCY_HEADER = "Idempotency-Key"


def idempotent_response(
    request: Request, scope: str, operation: Callable[[], tuple[int, Any]]
) -> Response:
    """Run a mutating request once per Idempotency-Key; retries get the stored response."""
    key = request.headers.get(IDEMPOTENCY_HEADER)
    if not key:
        raise InvalidIdempotencyKey()
    actor = request.actor  # type: ignore[attr-defined]
    result = run_idempotent(
        user_id=actor.user_id,
        scope=scope,
        key=key,
        request_hash=payload_hash({"path": request.path, "body": request.data}),
        operation=operation,
    )
    response = Response(result.body, status=result.status)
    if result.replayed:
        response["Idempotent-Replayed"] = "true"
    return response
