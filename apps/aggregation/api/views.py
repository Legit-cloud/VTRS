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
    """War Room: headline figures per contest over everything the caller may see. Figures are
    provisional and based on party-captured data; they are not an official declaration."""

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


class ContestResultsView(StrictQueryParamsMixin, APIView):
    """Drill-down: LGA scorecards, ward lists and polling-unit lists for one contest. Omit
    `level` to start at the top of the caller's own scope."""

    required_permission = Perm.DASHBOARD_VIEW
    allowed_query_params = frozenset({"level", "parent_id", "measure"})

    @extend_schema(
        parameters=[
            OpenApiParameter("level", str, enum=["state", "lga", "ward", "pu"]),
            OpenApiParameter("parent_id", str, description="The area one level up"),
            MEASURE,
        ],
        responses={200: s.ContestResultsSerializer},
    )
    def get(self, request: Request, contest_id: UUID) -> Response:
        services.ensure_rows_for_contest(self.actor, contest_id)
        body = selectors.results(
            self.actor,
            contest_id,
            level=request.query_params.get("level"),
            parent_id=self.uuid_param("parent_id"),
            measure_raw=request.query_params.get("measure"),
        )
        return Response(s.ContestResultsSerializer(body).data)


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
    def get(self, request: Request, contest_id: UUID) -> Response:
        services.ensure_rows_for_contest(self.actor, contest_id)
        body = selectors.coverage_timeline(
            self.actor,
            contest_id,
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
