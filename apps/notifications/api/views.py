from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.views import StrictQueryParamsMixin
from apps.core.authz import AUTHENTICATED
from apps.core.domain.permissions import Perm
from apps.core.pagination import KeysetPagination
from apps.notifications import selectors, services

from . import serializers as s


class NotificationPagination(KeysetPagination):
    ordering = "-created_at"


def _row(n: Any) -> dict[str, Any]:
    return {
        "id": n.id,
        "kind": n.kind,
        "severity": n.severity,
        "title": n.title,
        "body": n.body,
        "link": n.data,
        "read_at": n.read_at,
        "created_at": n.created_at,
        "deliveries": [
            {
                "channel": d.channel,
                "status": d.status,
                "detail": d.detail,
                "sent_at": d.sent_at,
                "delivered_at": d.delivered_at,
            }
            for d in sorted(n.deliveries.all(), key=lambda d: d.channel)
        ],
    }


class NotificationListView(StrictQueryParamsMixin, ListAPIView):
    """The caller's own notifications, newest first, with where each one was delivered."""

    required_permission = AUTHENTICATED
    serializer_class = s.NotificationSerializer
    pagination_class = NotificationPagination
    allowed_query_params = frozenset({"unread"})

    def get_queryset(self) -> QuerySet:
        raw = self.request.query_params.get("unread")
        if raw not in {None, "true", "false"}:
            raise ValidationError({"unread": ["Use true or false."]})
        return selectors.own_notifications(
            self.actor, unread=None if raw is None else raw == "true"
        )

    @extend_schema(parameters=[OpenApiParameter("unread", bool)])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    def paginate_queryset(  # type: ignore[override]
        self, queryset: QuerySet
    ) -> list[dict[str, Any]] | None:
        page = super().paginate_queryset(queryset)
        return None if page is None else [_row(n) for n in page]


class UnreadCountView(APIView):
    required_permission = AUTHENTICATED

    @extend_schema(responses={200: s.UnreadCountSerializer})
    def get(self, request: Request) -> Response:
        return Response({"unread": selectors.unread_count(request.actor)})  # type: ignore[attr-defined]


class MarkReadView(APIView):
    required_permission = AUTHENTICATED

    @extend_schema(request=None, responses={200: s.NotificationSerializer})
    def post(self, request: Request, notification_id: UUID) -> Response:
        notification = services.mark_read(request.actor, notification_id)  # type: ignore[attr-defined]
        if notification is None:
            raise NotFound()
        return Response(s.NotificationSerializer(_row(notification)).data)


class MarkAllReadView(APIView):
    required_permission = AUTHENTICATED

    @extend_schema(request=None, responses={200: s.MarkedSerializer})
    def post(self, request: Request) -> Response:
        return Response({"marked": services.mark_all_read(request.actor)})  # type: ignore[attr-defined]


class PushTokenView(APIView):
    """The mobile app registers its push token for the device the session was opened on."""

    required_permission = Perm.RESULTS_SUBMIT

    @extend_schema(request=s.PushTokenSerializer, responses={204: None})
    def put(self, request: Request) -> Response:
        data = s.PushTokenSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.register_push_token(request.actor, data.validated_data["token"])  # type: ignore[attr-defined]
        return Response(status=204)
