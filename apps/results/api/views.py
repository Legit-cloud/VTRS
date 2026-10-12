from typing import Any
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
from apps.results import selectors, services

from . import serializers as s

MAX_STATUS_IDS = 50
IDEMPOTENCY_KEY = OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)


class SyncSubmissionsView(APIView):
    """Batch of up to 10 offline submissions. Always 200 with one outcome per item: SYNCED,
    REQUIRES_REVIEW (accepted, flagged) or FAILED (do not retry; correct as a new version).
    Retrying an item with the same version_id is safe and returns `replayed: true`."""

    required_permission = Perm.RESULTS_SUBMIT
    throttle_classes = (SubmitThrottle,)

    @extend_schema(
        request=s.SubmissionBatchSerializer, responses={200: s.SubmissionResultSerializer}
    )
    def post(self, request: Request) -> Response:
        batch = s.SubmissionBatchSerializer(data=request.data)
        batch.is_valid(raise_exception=True)
        actor = request.actor  # type: ignore[attr-defined]
        outcomes = []
        for raw in batch.validated_data["items"]:
            item = s.SubmissionItemSerializer(data=raw)
            if not item.is_valid():
                version_id = (
                    raw.get("version_id") if isinstance(raw.get("version_id"), str) else None
                )
                outcomes.append(
                    services.failed(
                        version_id, 400, "malformed", "The item is invalid.", item.errors
                    )
                )
                continue
            outcomes.append(services.submit(actor, item.validated_data, raw))
        return Response({"items": outcomes})


class SyncStatusView(StrictQueryParamsMixin, APIView):
    required_permission = Perm.RESULTS_SUBMIT
    allowed_query_params = frozenset({"ids"})

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "ids", str, description=f"Comma-separated version ids (max {MAX_STATUS_IDS})"
            )
        ],
        responses={200: s.SyncStatusSerializer(many=True)},
    )
    def get(self, request: Request) -> Response:
        raw = [p.strip() for p in request.query_params.get("ids", "").split(",") if p.strip()]
        if not raw or len(raw) > MAX_STATUS_IDS:
            raise ValidationError({"ids": [f"Give 1 to {MAX_STATUS_IDS} version ids."]})
        try:
            ids = [UUID(value) for value in raw]
        except ValueError:
            raise ValidationError({"ids": ["Every id must be a UUID."]}) from None
        return Response(selectors.sync_status(self.actor, ids))


def _person(user: Any) -> dict[str, Any]:
    return {"id": user.id, "name": user.full_name}


def _votes(version: Any) -> list[dict[str, Any]]:
    return [
        {
            "candidate_id": line.candidate_id,
            "party_acronym": line.candidate.party_acronym,
            "name": line.candidate.name,
            "votes": line.votes,
        }
        for line in sorted(version.vote_lines.all(), key=lambda v: v.candidate.ballot_order)
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

    @staticmethod
    def _row(v: Any) -> dict[str, Any]:
        return {
            "version_id": v.id,
            "contest_id": v.contest_id,
            "contest_title": v.contest.title,
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
            "votes": _votes(v),
            "flags": [f for f in _flags(v) if f["status"] == "OPEN"],
            "submitted_by": _person(v.submitted_by),
            "server_received_at": v.server_received_at,
        }


class PuHistoryView(APIView):
    """Every version a polling unit's result has had for one contest, oldest first."""

    required_permission = Perm.DASHBOARD_VIEW

    @extend_schema(responses={200: s.PuHistorySerializer})
    def get(self, request: Request, contest_id: UUID, polling_unit_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        pu_result = selectors.pu_history(actor, contest_id, polling_unit_id)
        if pu_result is None:
            raise NotFound()
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
                "votes": _votes(v),
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
                        "status": e.status,
                        "sha256": e.sha256_server or e.sha256_client,
                    }
                    for e in files
                ]
            versions.append(row)
        body = {
            "contest_id": pu_result.contest_id,
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
