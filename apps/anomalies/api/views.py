from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.anomalies import selectors, services
from apps.anomalies.domain.inline import Severity
from apps.anomalies.models import AnomalyFlag, FlagStatus
from apps.anomalies.routing import RULE_TITLES
from apps.core.api.idempotency import idempotent_response
from apps.core.api.views import StrictQueryParamsMixin
from apps.core.domain.permissions import Perm
from apps.core.pagination import KeysetPagination
from apps.elections import selectors as elections

from . import serializers as s

IDEMPOTENCY_KEY = OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)


def _flag_row(flag: AnomalyFlag) -> dict[str, Any]:
    return {
        "id": flag.id,
        "election_id": flag.election_id,
        "contest_id": flag.contest_id,
        "polling_unit_id": flag.polling_unit_id,
        "polling_unit_code": flag.polling_unit.inec_code,
        "polling_unit_name": flag.polling_unit.name,
        "ward_id": flag.ward_id,
        "ward_name": flag.ward.name,
        "lga_id": flag.lga_id,
        "lga_name": flag.lga.name,
        "result_version_id": flag.result_version_id,
        "rule_code": flag.rule_code,
        "title": RULE_TITLES.get(flag.rule_code, flag.rule_code),
        "severity": flag.severity,
        "status": flag.status,
        "details": flag.details,
        "escalation_level": flag.escalation_level,
        "sla_due_at": flag.sla_due_at,
        "assigned_to_id": flag.assigned_to_id,
        "acknowledged_at": flag.acknowledged_at,
        "resolved_at": flag.resolved_at,
        "resolution_note": flag.resolution_note,
        "created_at": flag.created_at,
    }


def _detail(flag: AnomalyFlag) -> dict[str, Any]:
    row = _flag_row(flag)
    row["events"] = [
        {
            "action": e.action,
            "from_status": e.from_status,
            "to_status": e.to_status,
            "actor_id": e.actor_id,
            "note": e.note,
            "details": e.details,
            "at": e.at,
        }
        for e in sorted(flag.events.all(), key=lambda e: e.at)
    ]
    return row


class FlagPagination(KeysetPagination):
    ordering = "-created_at"


class FlagListView(StrictQueryParamsMixin, ListAPIView):
    """Flags for an election inside the caller's scope, newest first."""

    required_permission = Perm.ANOMALIES_VIEW
    serializer_class = s.FlagSerializer
    pagination_class = FlagPagination
    allowed_query_params = frozenset(
        {"status", "severity", "rule_code", "contest_id", "lga_id", "ward_id", "assigned_to_me"}
    )

    def get_queryset(self) -> QuerySet:
        election = elections.election_for(self.actor, self.kwargs["election_id"])
        qs = selectors.flags_for(self.actor).filter(election_id=election.id)
        params = self.request.query_params
        if status := params.get("status"):
            if status not in FlagStatus.values:
                raise ValidationError({"status": [f"Use one of {sorted(FlagStatus.values)}."]})
            qs = qs.filter(status=status)
        if severity := params.get("severity"):
            if severity not in {sv.value for sv in Severity}:
                raise ValidationError({"severity": ["Unknown severity."]})
            qs = qs.filter(severity=severity)
        if rule := params.get("rule_code"):
            qs = qs.filter(rule_code=rule)
        for name in ("contest_id", "lga_id", "ward_id"):
            if (value := self.uuid_param(name)) is not None:
                qs = qs.filter(**{name: value})
        if params.get("assigned_to_me") == "true":
            qs = qs.filter(assigned_to_id=self.actor.user_id)
        return qs

    def paginate_queryset(  # type: ignore[override]
        self, queryset: QuerySet
    ) -> list[dict[str, Any]] | None:
        page = super().paginate_queryset(queryset)
        return None if page is None else [_flag_row(f) for f in page]


class FlagSummaryView(APIView):
    required_permission = Perm.ANOMALIES_VIEW

    @extend_schema(responses={200: s.FlagSummarySerializer})
    def get(self, request: Request, election_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        election = elections.election_for(actor, election_id)
        return Response(s.FlagSummarySerializer(selectors.summary(actor, election.id)).data)


class FlagDetailView(APIView):
    required_permission = Perm.ANOMALIES_VIEW

    @extend_schema(responses={200: s.FlagDetailSerializer})
    def get(self, request: Request, flag_id: UUID) -> Response:
        flag = selectors.flag_for(request.actor, flag_id)  # type: ignore[attr-defined]
        return Response(s.FlagDetailSerializer(_detail(flag)).data)


class _FlagAction(APIView):
    """Base for the POST actions: load the flag in scope, run the action once per key, return
    the flag with its history."""

    scope = ""
    serializer: type[s.StrictSerializer] | None = None  # type: ignore[name-defined]

    def run(self, actor: Any, flag: AnomalyFlag, data: dict[str, Any]) -> AnomalyFlag:
        raise NotImplementedError

    def post(self, request: Request, flag_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        data: dict[str, Any] = {}
        if self.serializer is not None:
            parsed = self.serializer(data=request.data)
            parsed.is_valid(raise_exception=True)
            data = dict(parsed.validated_data)
        flag = selectors.flag_for(actor, flag_id)

        def operation() -> tuple[int, dict]:
            changed = self.run(actor, flag, data)
            fresh = selectors.flag_for(actor, changed.id)
            return 200, dict(s.FlagDetailSerializer(_detail(fresh)).data)

        return idempotent_response(request, f"{self.scope}.{flag_id}", operation)


class FlagAcknowledgeView(_FlagAction):
    required_permission = Perm.ANOMALIES_VIEW
    scope = "flags.ack"

    @extend_schema(
        request=None, responses={200: s.FlagDetailSerializer}, parameters=[IDEMPOTENCY_KEY]
    )
    def post(self, request: Request, flag_id: UUID) -> Response:
        return super().post(request, flag_id)

    def run(self, actor: Any, flag: AnomalyFlag, data: dict[str, Any]) -> AnomalyFlag:
        return services.acknowledge(actor, flag)


class FlagCommentView(_FlagAction):
    required_permission = Perm.ANOMALIES_VIEW
    scope = "flags.comment"
    serializer = s.NoteSerializer

    @extend_schema(
        request=s.NoteSerializer,
        responses={200: s.FlagDetailSerializer},
        parameters=[IDEMPOTENCY_KEY],
    )
    def post(self, request: Request, flag_id: UUID) -> Response:
        return super().post(request, flag_id)

    def run(self, actor: Any, flag: AnomalyFlag, data: dict[str, Any]) -> AnomalyFlag:
        return services.comment(actor, flag, data["note"])


class FlagAssignView(_FlagAction):
    required_permission = Perm.ANOMALIES_RESOLVE
    scope = "flags.assign"
    serializer = s.AssignSerializer

    @extend_schema(
        request=s.AssignSerializer,
        responses={200: s.FlagDetailSerializer},
        parameters=[IDEMPOTENCY_KEY],
    )
    def post(self, request: Request, flag_id: UUID) -> Response:
        return super().post(request, flag_id)

    def run(self, actor: Any, flag: AnomalyFlag, data: dict[str, Any]) -> AnomalyFlag:
        return services.assign(actor, flag, data["assignee_id"])


class FlagResolveView(_FlagAction):
    required_permission = Perm.ANOMALIES_RESOLVE
    scope = "flags.resolve"
    serializer = s.ResolveSerializer

    @extend_schema(
        request=s.ResolveSerializer,
        responses={200: s.FlagDetailSerializer},
        parameters=[IDEMPOTENCY_KEY],
    )
    def post(self, request: Request, flag_id: UUID) -> Response:
        return super().post(request, flag_id)

    def run(self, actor: Any, flag: AnomalyFlag, data: dict[str, Any]) -> AnomalyFlag:
        return services.resolve(actor, flag, outcome=data["outcome"], note=data["note"])


class FlagReopenView(_FlagAction):
    required_permission = Perm.ANOMALIES_RESOLVE
    scope = "flags.reopen"
    serializer = s.NoteSerializer

    @extend_schema(
        request=s.NoteSerializer,
        responses={200: s.FlagDetailSerializer},
        parameters=[IDEMPOTENCY_KEY],
    )
    def post(self, request: Request, flag_id: UUID) -> Response:
        return super().post(request, flag_id)

    def run(self, actor: Any, flag: AnomalyFlag, data: dict[str, Any]) -> AnomalyFlag:
        return services.reopen(actor, flag, data["note"])
