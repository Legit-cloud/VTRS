from typing import Any, ClassVar
from uuid import UUID

from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.generics import ListAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.idempotency import idempotent_response
from apps.core.api.views import StrictQueryParamsMixin
from apps.core.authz import AUTHENTICATED
from apps.core.pagination import KeysetPagination
from apps.reports import selectors, services

from . import serializers as s

IDEMPOTENCY_KEY = OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)


def _row(job: Any) -> dict[str, Any]:
    return {
        "id": job.id,
        "kind": job.kind,
        "format": job.format,
        "status": job.status,
        "params": job.params,
        "filename": job.filename,
        "size": job.size,
        "sha256": job.sha256,
        "manifest_sha256": job.manifest_sha256,
        "row_count": job.row_count,
        "file_count": job.file_count,
        "error": job.error,
        "requested_by_id": job.requested_by_id,
        "requested_at": job.requested_at,
        "finished_at": job.finished_at,
        "expires_at": job.expires_at,
        "download_count": job.download_count,
    }


class ExportPagination(KeysetPagination):
    ordering = "-requested_at"


class ExportListView(StrictQueryParamsMixin, ListAPIView):
    """Your exports (an organization admin sees everyone's). POST requests a new one: the
    file is built in the background, and a short-lived link is issued once it is ready."""

    required_permissions: ClassVar[dict[str, str]] = {"GET": AUTHENTICATED, "POST": AUTHENTICATED}
    serializer_class = s.ExportJobSerializer
    pagination_class = ExportPagination
    allowed_query_params = frozenset({"status"})

    def get_queryset(self) -> QuerySet:
        qs = selectors.exports_for(self.actor)
        if status := self.request.query_params.get("status"):
            qs = qs.filter(status=status)
        return qs

    def paginate_queryset(  # type: ignore[override]
        self, queryset: QuerySet
    ) -> list[dict[str, Any]] | None:
        page = super().paginate_queryset(queryset)
        return None if page is None else [_row(j) for j in page]

    @extend_schema(
        request=s.ExportRequestSerializer,
        responses={202: s.ExportJobSerializer},
        parameters=[IDEMPOTENCY_KEY],
    )
    def post(self, request: Request) -> Response:
        data = s.ExportRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        body = dict(data.validated_data)
        kind, fmt = body.pop("kind"), body.pop("format")

        def operation() -> tuple[int, dict]:
            job = services.request_export(self.actor, kind=kind, fmt=fmt, params=body)
            return 202, dict(s.ExportJobSerializer(_row(job)).data)

        return idempotent_response(request, "exports.request", operation)


class ExportDetailView(APIView):
    required_permission = AUTHENTICATED

    @extend_schema(responses={200: s.ExportJobSerializer})
    def get(self, request: Request, job_id: UUID) -> Response:
        job = selectors.export_for(request.actor, job_id)  # type: ignore[attr-defined]
        return Response(s.ExportJobSerializer(_row(job)).data)


class ExportDownloadView(APIView):
    """A 60-second link to the finished file. Needs a fresh second factor."""

    required_permission = AUTHENTICATED

    @extend_schema(request=None, responses={200: s.DownloadSerializer})
    def post(self, request: Request, job_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        job = selectors.export_for(actor, job_id)
        return Response(s.DownloadSerializer(services.download_url(actor, job)).data)
