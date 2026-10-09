from typing import Any
from uuid import UUID

from django.db import connection
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.domain.actor import Actor
from apps.core.errors import UnknownQueryParameter, problem_response


class StrictQueryParamsMixin:
    """Rejects query parameters a view does not explicitly allow (spec section 9)."""

    allowed_query_params: frozenset[str] = frozenset()
    pagination_query_params = frozenset({"cursor", "limit"})

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)  # type: ignore[misc]
        unknown = set(request.query_params) - self.allowed_query_params
        unknown -= self.pagination_query_params
        if unknown:
            raise UnknownQueryParameter(
                detail=f"Unknown query parameter(s): {', '.join(sorted(unknown))}",
                code="unknown_query_parameter",
            )

    @property
    def actor(self) -> Actor:
        return self.request.actor  # type: ignore[attr-defined]

    def uuid_param(self, name: str) -> UUID | None:
        raw = self.request.query_params.get(name)  # type: ignore[attr-defined]
        if raw is None:
            return None
        try:
            return UUID(raw)
        except ValueError:
            raise ValidationError({name: ["Must be a UUID."]}) from None


class LiveView(APIView):
    public = True
    authentication_classes = ()

    def get(self, request: Request) -> Response:
        return Response({"status": "ok"})


class ReadyView(APIView):
    public = True
    authentication_classes = ()

    def get(self, request: Request) -> Response:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except Exception:
            return problem_response(503, "not_ready", "A dependency is unavailable.")
        return Response({"status": "ready"})


class ServerTimeView(APIView):
    """Lets clients measure clock skew; `server_received_at` stays authoritative."""

    public = True
    authentication_classes = ()

    def get(self, request: Request) -> Response:
        return Response({"now": timezone.now().isoformat()})
