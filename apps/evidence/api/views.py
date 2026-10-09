from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.domain.permissions import Perm
from apps.evidence import selectors, services
from apps.results import selectors as results
from apps.results.api.serializers import EvidenceManifestSerializer, EvidenceUploadEntrySerializer


class UploadRequestSerializer(EvidenceManifestSerializer):
    version_id = serializers.UUIDField()


class EvidenceStateSerializer(serializers.Serializer):
    evidence_id = serializers.UUIDField()
    status = serializers.CharField()


class DownloadUrlSerializer(serializers.Serializer):
    url = serializers.CharField()
    expires_in = serializers.IntegerField()


class UploadRequestView(APIView):
    """Request a presigned upload for a photo of your own submission (or a fresh URL)."""

    required_permission = Perm.RESULTS_SUBMIT

    @extend_schema(request=UploadRequestSerializer, responses={200: EvidenceUploadEntrySerializer})
    def post(self, request: Request) -> Response:
        serializer = UploadRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        actor = request.actor  # type: ignore[attr-defined]
        version = results.own_version(actor, data["version_id"])
        if version is None:
            raise NotFound()
        return Response(services.request_upload(actor, version, data))


class UploadCompleteView(APIView):
    required_permission = Perm.RESULTS_SUBMIT

    @extend_schema(request=None, responses={200: EvidenceStateSerializer})
    def post(self, request: Request, evidence_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        evidence = services.complete_upload(actor, selectors.own_upload(actor, evidence_id))
        return Response({"evidence_id": str(evidence.id), "status": evidence.status})


class DownloadUrlView(APIView):
    """A 60-second download link. Issuing it is recorded in the file's chain of custody."""

    required_permission = Perm.EVIDENCE_VIEW

    @extend_schema(request=None, responses={200: DownloadUrlSerializer})
    def post(self, request: Request, evidence_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        return Response(services.download_url(actor, selectors.viewable(actor, evidence_id)))
