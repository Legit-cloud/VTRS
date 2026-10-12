from datetime import timedelta
from typing import Any

from django.db.models import QuerySet
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView

from apps.audit import selectors
from apps.core.api.views import StrictQueryParamsMixin
from apps.core.domain.permissions import Perm
from apps.core.pagination import KeysetPagination


class AuditEventSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    at = serializers.DateTimeField()
    action = serializers.CharField()
    object_type = serializers.CharField()
    object_id = serializers.CharField()
    actor_id = serializers.UUIDField(allow_null=True)
    actor_role = serializers.CharField()
    ip = serializers.CharField(allow_null=True)
    request_id = serializers.CharField()
    diff = serializers.DictField()


class AuditPagination(KeysetPagination):
    ordering = "-at"


def _when(raw: str | None, default: Any, name: str) -> Any:
    if raw is None:
        return default
    from django.utils.dateparse import parse_datetime

    parsed = parse_datetime(raw)
    if parsed is None or parsed.tzinfo is None:
        raise ValidationError({name: ["Use an ISO timestamp with a time zone offset."]})
    return parsed


class AuditEventListView(StrictQueryParamsMixin, ListAPIView):
    """The organization's audit trail, newest first. Defaults to the last 24 hours; the window
    is at most 31 days."""

    required_permission = Perm.AUDIT_VIEW
    serializer_class = AuditEventSerializer
    pagination_class = AuditPagination
    allowed_query_params = frozenset(
        {"since", "until", "action", "actor_id", "object_type", "object_id"}
    )

    def get_queryset(self) -> QuerySet:
        params = self.request.query_params
        now = timezone.now()
        until = _when(params.get("until"), now, "until")
        since = _when(params.get("since"), until - timedelta(hours=24), "since")
        return selectors.events_for(
            self.actor,
            since=since,
            until=until,
            action=params.get("action"),
            actor_id=self.uuid_param("actor_id"),
            object_type=params.get("object_type"),
            object_id=params.get("object_id"),
        )

    @extend_schema(
        parameters=[
            OpenApiParameter("since", str, description="ISO timestamp, default 24 h before until"),
            OpenApiParameter("until", str, description="ISO timestamp, default now"),
            OpenApiParameter("action", str, description="Action prefix, e.g. result."),
            OpenApiParameter("actor_id", str),
            OpenApiParameter("object_type", str),
            OpenApiParameter("object_id", str),
        ]
    )
    def get(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        return super().get(request, *args, **kwargs)
