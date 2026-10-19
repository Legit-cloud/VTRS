import hmac
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.parsers import FormParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.views import StrictQueryParamsMixin
from apps.core.authz import AUTHENTICATED
from apps.core.pagination import KeysetPagination
from apps.notifications import selectors, services
from apps.notifications.providers import twilio_signature

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


class TwilioStatusWebhookView(APIView):
    """Twilio delivery receipts. Public, so the signature is the only gate: anything that does
    not verify is refused before it can touch a delivery record."""

    public = True
    authentication_classes = ()
    parser_classes = (FormParser,)

    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request) -> Response:
        token = settings.VTRS_TWILIO_AUTH_TOKEN
        base = settings.VTRS_PUBLIC_BASE_URL.rstrip("/")
        if not (token and base):
            raise PermissionDenied()
        params = {key: str(value) for key, value in request.POST.items()}
        expected = twilio_signature(base + request.path, params, token)
        supplied = request.headers.get("X-Twilio-Signature", "")
        if not hmac.compare_digest(expected, supplied):
            raise PermissionDenied()
        status = params.get("MessageStatus", "")
        message_id = params.get("MessageSid", "")
        if message_id and status in {"delivered", "read", "undelivered", "failed"}:
            channel = "WHATSAPP" if params.get("To", "").startswith("whatsapp:") else "SMS"
            services.record_receipt(
                channel=channel,
                provider_message_id=message_id,
                delivered=status in {"delivered", "read"},
                detail=params.get("ErrorCode", "") or status,
            )
        return Response(status=204)
