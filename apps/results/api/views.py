from typing import Any, ClassVar
from uuid import UUID

from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.api.throttles import SubmitThrottle
from apps.core.api.idempotency import idempotent_response
from apps.core.api.views import StrictQueryParamsMixin
from apps.core.domain.permissions import Perm
from apps.core.pagination import KeysetPagination
from apps.elections import selectors as elections
from apps.elections.api.serializers import ConfigIssueSerializer
from apps.results import selectors, services

from . import serializers as s

IDEMPOTENCY_KEY = OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)


class SubmissionView(APIView):
    """Submit the numbers for one polling unit (spec section 10). Sending the same
    `version_id` again (a retry or a double tap) is safe: it returns the stored outcome with
    `replayed: true` and never creates a second result. The response status is the outcome's
    `http_status`; refused submissions say why in `code` and `detail`."""

    required_permission = Perm.RESULTS_SUBMIT
    throttle_classes = (SubmitThrottle,)

    @extend_schema(
        request=s.SubmissionSerializer,
        responses={
            200: s.SubmissionOutcomeSerializer,
            400: s.SubmissionOutcomeSerializer,
            403: s.SubmissionOutcomeSerializer,
            404: s.SubmissionOutcomeSerializer,
            409: s.SubmissionOutcomeSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        raw = request.data if isinstance(request.data, dict) else {}
        item = s.SubmissionSerializer(data=request.data)
        if not item.is_valid():
            version_id = raw.get("version_id") if isinstance(raw.get("version_id"), str) else None
            outcome = services.failed(
                version_id, 400, "malformed", "The submission is invalid.", item.errors
            )
        else:
            outcome = services.submit(actor, item.validated_data, raw)
        return Response(outcome, status=outcome["http_status"])


class SubmissionStatusView(APIView):
    """One of my submissions: its review state, whether the sheet is attached, and why it was
    rejected if it was."""

    required_permission = Perm.RESULTS_SUBMIT

    @extend_schema(responses={200: s.SubmissionStatusSerializer})
    def get(self, request: Request, version_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        body = selectors.submission_status(actor, version_id)
        return Response(s.SubmissionStatusSerializer(body).data)


class MyAssignmentsView(APIView):
    """What the agent sees before capture (FR-6.2.5, AC-04): each assigned election and polling
    unit, with the result that currently counts there and the agent's latest submission."""

    required_permission = Perm.RESULTS_SUBMIT

    @extend_schema(responses={200: s.MyAssignmentWithResultSerializer(many=True)})
    def get(self, request: Request) -> Response:
        rows = selectors.my_assignments(request.actor)  # type: ignore[attr-defined]
        return Response(s.MyAssignmentWithResultSerializer(rows, many=True).data)


class ResultFormView(APIView):
    """The result form for an assigned unit (FR-6.5.1, AC-16): exactly the configured parties,
    in the admin's order, each with its candidate. Read-only apart from the numbers."""

    required_permission = Perm.RESULTS_SUBMIT

    @extend_schema(responses={200: s.ResultFormSerializer})
    def get(self, request: Request, election_id: UUID, polling_unit_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        body = selectors.result_form(actor, election_id, polling_unit_id)
        return Response(s.ResultFormSerializer(body).data)


class IssuePagination(KeysetPagination):
    ordering = "-created_at"


class ConfigIssuesView(StrictQueryParamsMixin, ListAPIView):
    """GET: "party missing" / "contestant missing" tasks for admins (FR-6.3.7).
    POST: an agent reports one from the result form of an assigned unit. Neither ever creates
    or changes a party or contestant."""

    required_permissions: ClassVar[dict[str, str]] = {
        "GET": Perm.ELECTIONS_CONFIGURE,
        "POST": Perm.RESULTS_SUBMIT,
    }
    serializer_class = ConfigIssueSerializer
    pagination_class = IssuePagination
    allowed_query_params = frozenset({"status"})

    def get_queryset(self) -> QuerySet:
        election = elections.election_for(self.actor, self.kwargs["election_id"])
        qs = elections.issues_for(self.actor, election)
        status = self.request.query_params.get("status")
        if status is not None:
            if status not in {"OPEN", "RESOLVED"}:
                raise ValidationError({"status": ["Use OPEN or RESOLVED."]})
            qs = qs.filter(status=status)
        return qs

    @extend_schema(
        request=s.ConfigIssueReportSerializer,
        responses={201: ConfigIssueSerializer},
        parameters=[IDEMPOTENCY_KEY],
    )
    def post(self, request: Request, election_id: UUID) -> Response:
        data = s.ConfigIssueReportSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        actor = self.actor

        def operation() -> tuple[int, dict]:
            issue = services.report_config_issue(actor, election_id, **data.validated_data)
            return 201, dict(ConfigIssueSerializer(issue).data)

        return idempotent_response(request, f"config_issues.report.{election_id}", operation)


def _person(user: Any) -> dict[str, Any]:
    return {"id": user.id, "name": user.full_name}


def _votes(version: Any, order: dict[Any, int]) -> list[dict[str, Any]]:
    """Vote lines in the election's party order."""
    return [
        {
            "candidate_id": line.candidate_id,
            "party_id": line.candidate.party_id,
            "party_abbreviation": line.candidate.party.abbreviation,
            "name": line.candidate.name,
            "votes": line.votes,
        }
        for line in sorted(
            version.vote_lines.all(),
            key=lambda v: (order.get(v.candidate.party_id, 999), v.candidate.party.abbreviation),
        )
    ]


def _evidence(version: Any) -> list[dict[str, Any]]:
    return [
        {"evidence_id": e.id, "kind": e.kind, "mime": e.mime, "status": e.status}
        for e in sorted(version.evidence.all(), key=lambda e: e.created_at)
    ]


def _flags(version: Any) -> list[dict[str, Any]]:
    return [
        {"id": f.id, "rule_code": f.rule_code, "severity": f.severity, "status": f.status}
        for f in sorted(version.flags.all(), key=lambda f: (f.created_at, f.rule_code))
    ]


def _totals(version: Any) -> dict[str, Any]:
    return {
        "accredited": version.accredited,
        "valid": version.valid,
        "rejected": version.rejected,
        "total_cast": version.total_cast,
    }


class ReviewView(APIView):
    """Approve or reject the version that currently counts for a polling unit. A rejection
    needs a reason; the agent then resubmits a corrected version."""

    required_permission = Perm.RESULTS_REVIEW

    @extend_schema(
        request=s.ReviewRequestSerializer,
        responses={200: s.ReviewOutcomeSerializer},
        parameters=[IDEMPOTENCY_KEY],
    )
    def post(self, request: Request, version_id: UUID) -> Response:
        data = s.ReviewRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        actor = request.actor  # type: ignore[attr-defined]

        def operation() -> tuple[int, dict]:
            outcome = services.review(actor, version_id, **data.validated_data)
            return 200, dict(s.ReviewOutcomeSerializer(outcome).data)

        return idempotent_response(request, f"results.review.{version_id}", operation)


class ReviewQueuePagination(KeysetPagination):
    ordering = "server_received_at"


class ReviewQueueView(StrictQueryParamsMixin, ListAPIView):
    required_permission = Perm.RESULTS_REVIEW
    serializer_class = s.ReviewQueueItemSerializer
    pagination_class = ReviewQueuePagination
    allowed_query_params = frozenset({"contest_id", "ward_id", "lga_id", "flagged"})

    def get_queryset(self) -> QuerySet:
        election = elections.election_for(self.actor, self.kwargs["election_id"])
        self._order = {
            p.party_id: p.ballot_order for p in elections.election_parties(self.actor, election)
        }
        qs = selectors.review_queue(self.actor, election.id)
        for name in ("contest_id", "ward_id", "lga_id"):
            if (value := self.uuid_param(name)) is not None:
                qs = qs.filter(**{name: value})
        flagged = self.request.query_params.get("flagged")
        if flagged is not None:
            if flagged not in {"true", "false"}:
                raise ValidationError({"flagged": ["Use true or false."]})
            qs = qs.filter(state="REQUIRES_REVIEW" if flagged == "true" else "SUBMITTED")
        return qs

    def paginate_queryset(  # type: ignore[override]
        self, queryset: QuerySet
    ) -> list[dict[str, Any]] | None:
        page = super().paginate_queryset(queryset)
        return None if page is None else [self._row(v) for v in page]

    def _row(self, v: Any) -> dict[str, Any]:
        return {
            "version_id": v.id,
            "contest_id": v.contest_id,
            "constituency_name": v.contest.constituency.name,
            "polling_unit_id": v.polling_unit_id,
            "polling_unit_code": v.polling_unit.inec_code,
            "polling_unit_name": v.polling_unit.name,
            "ward_id": v.ward_id,
            "ward_name": v.ward.name,
            "lga_id": v.lga_id,
            "lga_name": v.lga.name,
            "version_no": v.version_no,
            "state": v.state,
            "totals": _totals(v),
            "votes": _votes(v, self._order),
            "flags": [f for f in _flags(v) if f["status"] == "OPEN"],
            "completion": selectors.completion(v),
            "evidence": _evidence(v),
            "submitted_by": _person(v.submitted_by),
            "server_received_at": v.server_received_at,
        }


class PuHistoryView(APIView):
    """Every version a polling unit's result has had for one election, oldest first."""

    required_permission = Perm.DASHBOARD_VIEW

    @extend_schema(responses={200: s.PuHistorySerializer})
    def get(self, request: Request, election_id: UUID, polling_unit_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        election = elections.election_for(actor, election_id)
        pu_result = selectors.pu_history(actor, election.id, polling_unit_id)
        if pu_result is None:
            raise NotFound()
        order = {p.party_id: p.ballot_order for p in elections.election_parties(actor, election)}
        see_evidence = actor.has_perm(Perm.EVIDENCE_VIEW)
        versions = []
        for v in pu_result.versions.all():
            files = sorted(v.evidence.all(), key=lambda e: e.created_at)
            row: dict[str, Any] = {
                "version_id": v.id,
                "version_no": v.version_no,
                "state": v.state,
                "is_head": pu_result.head_version_id == v.id,
                "parent_version_id": v.parent_version_id,
                "totals": _totals(v),
                "votes": _votes(v, order),
                "flags": _flags(v),
                "reviews": [
                    {
                        "decision": r.decision,
                        "from_state": r.from_state,
                        "reason": r.reason,
                        "acknowledged_flags": r.acknowledged_flags,
                        "decided_by": _person(r.decided_by),
                        "decided_at": r.decided_at,
                    }
                    for r in v.reviews.all()
                ],
                "completion": selectors.completion(v),
                "evidence_count": len(files),
                "submitted_by": _person(v.submitted_by),
                "device_captured_at": v.device_captured_at,
                "server_received_at": v.server_received_at,
                "gps": (
                    {"lat": v.gps_lat, "lng": v.gps_lng, "accuracy_m": v.gps_accuracy_m}
                    if v.gps_lat is not None
                    else None
                ),
                "payload_hash": v.payload_hash,
            }
            if see_evidence:
                row["evidence"] = [
                    {
                        "evidence_id": e.id,
                        "kind": e.kind,
                        "mime": e.mime,
                        "status": e.status,
                        "sha256": e.sha256_server or e.sha256_client,
                    }
                    for e in files
                ]
            versions.append(row)
        body = {
            "election_id": pu_result.election_id,
            "contest_id": pu_result.contest_id,
            "constituency_name": pu_result.contest.constituency.name,
            "polling_unit_id": pu_result.polling_unit_id,
            "polling_unit_code": pu_result.polling_unit.inec_code,
            "polling_unit_name": pu_result.polling_unit.name,
            "ward_id": pu_result.ward_id,
            "lga_id": pu_result.lga_id,
            "status": pu_result.status,
            "head_version_id": pu_result.head_version_id,
            "versions": versions,
        }
        return Response(s.PuHistorySerializer(body).data)
