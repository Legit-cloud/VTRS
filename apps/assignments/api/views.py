from uuid import UUID

from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.generics import ListAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.assignments import selectors, services
from apps.assignments.models import AgentAssignment
from apps.core.api.idempotency import idempotent_response
from apps.core.api.views import StrictQueryParamsMixin
from apps.core.domain.permissions import Perm

from . import serializers as s

IDEMPOTENCY_KEY = OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)


class AssignmentListView(StrictQueryParamsMixin, ListAPIView):
    required_permission = Perm.ASSIGNMENTS_MANAGE
    serializer_class = s.AssignmentSerializer
    allowed_query_params = frozenset({"election", "agent", "polling_unit", "status"})

    def get_queryset(self) -> QuerySet[AgentAssignment]:
        qs = selectors.assignments_for(self.actor)
        for param, field in (
            ("election", "election_id"),
            ("agent", "agent_id"),
            ("polling_unit", "polling_unit_id"),
        ):
            if (value := self.uuid_param(param)) is not None:
                qs = qs.filter(**{field: value})
        if status := self.request.query_params.get("status"):
            qs = qs.filter(status=status)
        return qs

    @extend_schema(
        request=s.AssignmentCreateSerializer,
        responses={201: s.AssignmentSerializer},
        parameters=[IDEMPOTENCY_KEY],
    )
    def post(self, request: Request) -> Response:
        serializer = s.AssignmentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> tuple[int, dict]:
            assignment = services.assign(self.actor, **serializer.validated_data)
            return 201, dict(s.AssignmentSerializer(assignment).data)

        return idempotent_response(request, "assignments.create", operation)


class AssignmentRevokeView(APIView):
    required_permission = Perm.ASSIGNMENTS_MANAGE

    @extend_schema(
        request=None, responses={200: s.AssignmentSerializer}, parameters=[IDEMPOTENCY_KEY]
    )
    def post(self, request: Request, assignment_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        assignment = selectors.assignment_for(actor, assignment_id)

        def operation() -> tuple[int, dict]:
            return 200, dict(s.AssignmentSerializer(services.revoke(actor, assignment)).data)

        return idempotent_response(request, "assignments.revoke", operation)


class MyAssignmentsView(APIView):
    """What the agent app shows before capture (FR-6.2.5, AC-04)."""

    required_permission = Perm.RESULTS_SUBMIT

    @extend_schema(responses={200: s.MyAssignmentSerializer(many=True)})
    def get(self, request: Request) -> Response:
        rows = selectors.my_assignments(request.actor)  # type: ignore[attr-defined]
        return Response(s.MyAssignmentSerializer(rows, many=True).data)
