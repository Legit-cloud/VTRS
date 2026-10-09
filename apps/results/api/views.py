from uuid import UUID

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.api.throttles import SubmitThrottle
from apps.core.api.views import StrictQueryParamsMixin
from apps.core.domain.permissions import Perm
from apps.results import selectors, services

from . import serializers as s

MAX_STATUS_IDS = 50


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
