from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.domain.permissions import Perm
from apps.operations import selectors


class HealthSerializer(serializers.Serializer):
    status = serializers.CharField()
    checked_at = serializers.DateTimeField()
    components = serializers.DictField()


class AnalyticsSerializer(serializers.Serializer):
    election_id = serializers.UUIDField()
    invitations = serializers.DictField(required=False)
    assignment = serializers.DictField()
    capture = serializers.DictField()
    submission = serializers.DictField()
    evidence = serializers.DictField()
    integrity = serializers.DictField()


class DataQualitySerializer(serializers.Serializer):
    polling_units = serializers.IntegerField()
    without_coordinates = serializers.IntegerField()
    without_registered_voters = serializers.IntegerField()
    coordinates_complete_pct = serializers.FloatField(allow_null=True)
    worst_lgas_for_coordinates = serializers.ListField(child=serializers.DictField())


class SystemHealthView(APIView):
    """Infrastructure checks and this organization's work in flight."""

    required_permission = Perm.SYSTEM_VIEW

    @extend_schema(responses={200: HealthSerializer})
    def get(self, request: Request) -> Response:
        return Response(selectors.system_health(request.actor))  # type: ignore[attr-defined]


class AnalyticsView(APIView):
    """Onboarding, capture, submission and integrity metrics for one election, inside your
    scope."""

    required_permission = Perm.DASHBOARD_VIEW

    @extend_schema(responses={200: AnalyticsSerializer})
    def get(self, request: Request, election_id: UUID) -> Response:
        return Response(selectors.analytics(request.actor, election_id))  # type: ignore[attr-defined]


class DataQualityView(APIView):
    required_permission = Perm.SYSTEM_VIEW

    @extend_schema(responses={200: DataQualitySerializer})
    def get(self, request: Request) -> Response:
        return Response(selectors.data_quality(request.actor))  # type: ignore[attr-defined]
