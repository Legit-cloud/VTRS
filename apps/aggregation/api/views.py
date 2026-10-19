from typing import Any
from uuid import UUID

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.aggregation import selectors, services
from apps.core.api.views import StrictQueryParamsMixin
from apps.core.domain.permissions import Perm
from apps.elections import selectors as elections
from apps.elections import services as election_services
from apps.elections.domain.rules import ElectionStatus
from apps.elections.models import Election

from . import serializers as s

MEASURE = OpenApiParameter(
    "measure",
    str,
    description="reported (every counting result) or verified (approved results only). "
    "Defaults to the election's count policy.",
    enum=["reported", "verified"],
)


class DashboardView(StrictQueryParamsMixin, APIView):
    """War room: every party and contestant side by side over everything the caller may see,
    with the leader status (ties and narrow margins named) and X of Y polling units reported.
    Figures are the party's own collection, not the official INEC count."""

    required_permission = Perm.DASHBOARD_VIEW
    allowed_query_params = frozenset({"measure"})

    @extend_schema(parameters=[MEASURE], responses={200: s.DashboardSerializer})
    def get(self, request: Request, election_id: UUID) -> Response:
        election = elections.election_for(self.actor, election_id)
        measure = selectors.parse_measure(request.query_params.get("measure"), election)
        services.ensure_rows_for_election(self.actor, election)
        return Response(
            s.DashboardSerializer(selectors.dashboard(self.actor, election, measure)).data
        )


class ElectionResultsView(StrictQueryParamsMixin, APIView):
    """Drill-down: state, LGA, ward and polling-unit rows for one election, each with every
    party's votes and its leader. Omit `level` to start at the top of the caller's scope."""

    required_permission = Perm.DASHBOARD_VIEW
    allowed_query_params = frozenset({"level", "parent_id", "measure"})

    @extend_schema(
        parameters=[
            OpenApiParameter("level", str, enum=["state", "lga", "ward", "pu"]),
            OpenApiParameter("parent_id", str, description="The area one level up"),
            MEASURE,
        ],
        responses={200: s.ElectionResultsSerializer},
    )
    def get(self, request: Request, election_id: UUID) -> Response:
        election = elections.election_for(self.actor, election_id)
        measure = selectors.parse_measure(request.query_params.get("measure"), election)
        services.ensure_rows_for_election(self.actor, election)
        body = selectors.results(
            self.actor,
            election,
            level=request.query_params.get("level"),
            parent_id=self.uuid_param("parent_id"),
            measure=measure,
        )
        return Response(s.ElectionResultsSerializer(body).data)


class CoverageTimelineView(StrictQueryParamsMixin, APIView):
    required_permission = Perm.DASHBOARD_VIEW
    allowed_query_params = frozenset({"interval", "parent_id"})

    @extend_schema(
        parameters=[
            OpenApiParameter("interval", str, enum=["minute", "hour"]),
            OpenApiParameter("parent_id", str),
        ],
        responses={200: s.CoverageTimelineSerializer},
    )
    def get(self, request: Request, election_id: UUID) -> Response:
        election = elections.election_for(self.actor, election_id)
        services.ensure_rows_for_election(self.actor, election)
        body = selectors.coverage_timeline(
            self.actor,
            election,
            interval=request.query_params.get("interval", "hour"),
            parent_id=self.uuid_param("parent_id"),
        )
        return Response(s.CoverageTimelineSerializer(body).data)


class ReconciliationView(APIView):
    """What stands between a closed election and RECONCILED."""

    required_permission = Perm.ELECTIONS_CONFIGURE

    @extend_schema(responses={200: s.ReadinessSerializer})
    def get(self, request: Request, election_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        election = elections.election_for(actor, election_id)
        return Response(s.ReadinessSerializer(services.readiness(actor, election)).data)


class ElectionReconcileView(APIView):
    """Freeze the rollups of a closed election and mark it RECONCILED. Needs a fresh second
    factor. Results can no longer change afterwards."""

    required_permission = Perm.ELECTIONS_CONFIGURE

    @extend_schema(request=None, responses={200: s.ReconcileOutcomeSerializer})
    def post(self, request: Request, election_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        election = elections.election_for(actor, election_id)
        done: Election = election_services.transition(
            actor, election, ElectionStatus.RECONCILED, reconcile=services.reconcile
        )
        snapshot = done.reconciliation  # type: ignore[attr-defined]
        outcome: dict[str, Any] = {
            "election_id": done.id,
            "status": done.status,
            "snapshot_id": snapshot.id,
            "snapshot_sha256": snapshot.sha256,
            "reported_pus": snapshot.reported_pus,
            "verified_pus": snapshot.verified_pus,
            "reconciled_at": snapshot.reconciled_at,
        }
        return Response(s.ReconcileOutcomeSerializer(outcome).data)
