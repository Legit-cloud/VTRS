from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import OpenApiTypes, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.idempotency import idempotent_response
from apps.core.api.serializers import StrictSerializer
from apps.core.api.views import StrictQueryParamsMixin
from apps.core.domain.permissions import Perm
from apps.core.pagination import KeysetPagination
from apps.core.rls import system_context
from apps.notifications import services as notifications
from apps.organizations.models import Organization
from apps.platform_admin import selectors, services

TAG = ["platform"]


class OrganizationSerializer(serializers.ModelSerializer):
    people = serializers.IntegerField(read_only=True)
    agents = serializers.IntegerField(read_only=True)
    election_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Organization
        fields = (
            "id",
            "name",
            "legal_name",
            "status",
            "status_reason",
            "created_at",
            "verified_at",
            "approved_at",
            "people",
            "agents",
            "election_count",
        )


class DecisionSerializer(StrictSerializer):
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class ElectionRowSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    organization_id = serializers.UUIDField()
    organization_name = serializers.CharField(source="organization.name")
    name = serializers.CharField()
    status = serializers.CharField()
    election_date = serializers.DateField()
    locked_at = serializers.DateTimeField(allow_null=True)
    opened_at = serializers.DateTimeField(allow_null=True)
    closed_at = serializers.DateTimeField(allow_null=True)
    config_version = serializers.IntegerField()


class PlatformAuditSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    at = serializers.DateTimeField()
    organization_id = serializers.UUIDField(allow_null=True)
    action = serializers.CharField()
    object_type = serializers.CharField()
    object_id = serializers.CharField()
    actor_id = serializers.UUIDField(allow_null=True)
    actor_role = serializers.CharField()
    diff = serializers.DictField()


class _InSystemContext:
    """List views read across tenants, so the whole of the read runs in the system context."""

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        with system_context():
            return super().list(request, *args, **kwargs)  # type: ignore[misc]


class _Newest(KeysetPagination):
    ordering = "-id"


class _ByTime(KeysetPagination):
    ordering = "-at"


class OverviewView(APIView):
    required_permission = Perm.PLATFORM_MANAGE

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, tags=TAG)
    def get(self, request: Request) -> Response:
        with system_context():
            return Response(selectors.overview(request.actor))  # type: ignore[attr-defined]


class OrganizationListView(_InSystemContext, StrictQueryParamsMixin, ListAPIView):
    required_permission = Perm.PLATFORM_MANAGE
    serializer_class = OrganizationSerializer
    pagination_class = _Newest
    allowed_query_params = frozenset({"status"})

    def get_queryset(self) -> QuerySet[Organization]:
        return selectors.organizations(self.actor, status=self.request.query_params.get("status"))


class VerificationQueueView(_InSystemContext, StrictQueryParamsMixin, ListAPIView):
    required_permission = Perm.PLATFORM_MANAGE
    serializer_class = OrganizationSerializer
    pagination_class = _Newest

    def get_queryset(self) -> QuerySet[Organization]:
        return selectors.verification_queue(self.actor)


class OrganizationDetailView(APIView):
    required_permission = Perm.PLATFORM_MANAGE

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, tags=TAG)
    def get(self, request: Request, organization_id: UUID) -> Response:
        with system_context():
            detail = selectors.organization_detail(request.actor, organization_id)  # type: ignore[attr-defined]
            detail["organization"] = OrganizationSerializer(detail["organization"]).data
            return Response(detail)


class _DecisionView(APIView):
    required_permission = Perm.PLATFORM_MANAGE
    scope = ""
    needs_reason = False

    def decide(self, actor: Any, organization_id: UUID, reason: str) -> Organization:
        raise NotImplementedError

    @extend_schema(request=DecisionSerializer, responses={200: OrganizationSerializer}, tags=TAG)
    def post(self, request: Request, organization_id: UUID) -> Response:
        data = DecisionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        actor = request.actor  # type: ignore[attr-defined]

        def operation() -> tuple[int, dict]:
            org = self.decide(actor, organization_id, data.validated_data["reason"])
            with system_context():
                row = selectors.organizations(actor).get(id=org.id)
            return 200, dict(OrganizationSerializer(row).data)

        return idempotent_response(request, f"{self.scope}.{organization_id}", operation)


class ApproveView(_DecisionView):
    scope = "platform.approve"

    def decide(self, actor: Any, organization_id: UUID, reason: str) -> Organization:
        return services.approve(actor, organization_id)


class RejectView(_DecisionView):
    scope = "platform.reject"

    def decide(self, actor: Any, organization_id: UUID, reason: str) -> Organization:
        return services.reject(actor, organization_id, reason)


class SuspendView(_DecisionView):
    scope = "platform.suspend"

    def decide(self, actor: Any, organization_id: UUID, reason: str) -> Organization:
        return services.suspend(actor, organization_id, reason)


class ReinstateView(_DecisionView):
    scope = "platform.reinstate"

    def decide(self, actor: Any, organization_id: UUID, reason: str) -> Organization:
        return services.reinstate(actor, organization_id)


class ElectionListView(_InSystemContext, StrictQueryParamsMixin, ListAPIView):
    required_permission = Perm.PLATFORM_MANAGE
    serializer_class = ElectionRowSerializer
    pagination_class = _Newest
    allowed_query_params = frozenset({"status"})

    def get_queryset(self) -> QuerySet:
        return selectors.elections(self.actor, status=self.request.query_params.get("status"))


class MasterDataView(APIView):
    required_permission = Perm.PLATFORM_MANAGE

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, tags=TAG)
    def get(self, request: Request) -> Response:
        return Response(selectors.master_data(request.actor))  # type: ignore[attr-defined]


class MasterDataSearchView(StrictQueryParamsMixin, APIView):
    required_permission = Perm.PLATFORM_MANAGE
    allowed_query_params = frozenset({"q"})

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, tags=TAG)
    def get(self, request: Request) -> Response:
        rows = selectors.master_data_search(
            request.actor,  # type: ignore[attr-defined]
            request.query_params.get("q", ""),
        )
        return Response({"results": rows})


class _FileUpload(StrictSerializer):
    file = serializers.FileField()


class _MasterDataFileView(APIView):
    required_permission = Perm.PLATFORM_MANAGE
    parser_classes = (MultiPartParser,)

    def content(self, request: Request) -> bytes:
        data = _FileUpload(data=request.data)
        data.is_valid(raise_exception=True)
        upload = data.validated_data["file"]
        if upload.size > services.MAX_FILE_BYTES:
            raise ValidationError({"file": ["The file is larger than 8 MB."]})
        return bytes(upload.read())


class MasterDataPreviewView(_MasterDataFileView):
    @extend_schema(
        request={"multipart/form-data": _FileUpload},
        responses={200: OpenApiTypes.OBJECT},
        tags=TAG,
    )
    def post(self, request: Request) -> Response:
        return Response(
            services.preview_master_data(request.actor, self.content(request))  # type: ignore[attr-defined]
        )


class MasterDataImportView(_MasterDataFileView):
    @extend_schema(
        request={"multipart/form-data": _FileUpload},
        responses={200: OpenApiTypes.OBJECT},
        tags=TAG,
    )
    def post(self, request: Request) -> Response:
        return Response(
            services.import_master_data(request.actor, self.content(request))  # type: ignore[attr-defined]
        )


class MessagingView(StrictQueryParamsMixin, APIView):
    required_permission = Perm.PLATFORM_MANAGE
    allowed_query_params = frozenset({"hours"})

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, tags=TAG)
    def get(self, request: Request) -> Response:
        try:
            hours = int(request.query_params.get("hours", "24"))
        except ValueError:
            raise ValidationError({"hours": ["Must be a whole number."]}) from None
        hours = min(max(hours, 1), 24 * 14)
        with system_context():
            return Response(selectors.messaging(request.actor, hours=hours))  # type: ignore[attr-defined]


class MessagingTestSerializer(StrictSerializer):
    channel = serializers.ChoiceField(choices=["SMS", "EMAIL"])


class MessagingTestView(APIView):
    """Send a test message to the operator's own phone or email, through the live provider."""

    required_permission = Perm.PLATFORM_MANAGE

    @extend_schema(
        request=MessagingTestSerializer,
        responses={
            200: inline_serializer("MessagingTestResult", {"sent_to": serializers.CharField()})
        },
        tags=TAG,
    )
    def post(self, request: Request) -> Response:
        data = MessagingTestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        actor = request.actor  # type: ignore[attr-defined]

        def operation() -> tuple[int, dict]:
            return 200, notifications.send_test_message(actor, data.validated_data["channel"])

        return idempotent_response(request, "platform.messaging_test", operation)


class AuditListView(_InSystemContext, StrictQueryParamsMixin, ListAPIView):
    required_permission = Perm.PLATFORM_MANAGE
    serializer_class = PlatformAuditSerializer
    pagination_class = _ByTime
    allowed_query_params = frozenset({"organization_id", "action", "since", "until"})

    def _when(self, name: str) -> Any:
        raw = self.request.query_params.get(name)
        if raw is None:
            return None
        parsed = parse_datetime(raw)
        if parsed is None or parsed.tzinfo is None:
            raise ValidationError({name: ["Use an ISO timestamp with a time zone offset."]})
        return parsed

    def get_queryset(self) -> QuerySet:
        return selectors.audit_events(
            self.actor,
            organization_id=self.uuid_param("organization_id"),
            action=self.request.query_params.get("action"),
            since=self._when("since"),
            until=self._when("until"),
        )
