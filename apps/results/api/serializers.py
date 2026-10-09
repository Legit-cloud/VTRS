from rest_framework import serializers

from apps.core.api.serializers import StrictSerializer
from apps.evidence.domain.rules import ALLOWED_TYPES, MAX_BYTES, EvidenceKind

MAX_COUNT = 1_000_000
HEX64 = r"^[0-9a-fA-F]{64}$"


class TotalsSerializer(StrictSerializer):
    accredited = serializers.IntegerField(
        min_value=0, max_value=MAX_COUNT, required=False, allow_null=True
    )
    valid = serializers.IntegerField(min_value=0, max_value=MAX_COUNT)
    rejected = serializers.IntegerField(
        min_value=0, max_value=MAX_COUNT, required=False, allow_null=True
    )
    total_cast = serializers.IntegerField(
        min_value=0, max_value=MAX_COUNT, required=False, allow_null=True
    )


class VoteLineSerializer(StrictSerializer):
    candidate_id = serializers.UUIDField()
    votes = serializers.IntegerField(min_value=0, max_value=MAX_COUNT)


class GpsSerializer(StrictSerializer):
    lat = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=-90, max_value=90)
    lng = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=-180, max_value=180)
    accuracy_m = serializers.DecimalField(
        max_digits=8, decimal_places=2, min_value=0, required=False, allow_null=True
    )


class EvidenceManifestSerializer(StrictSerializer):
    evidence_id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=[k.value for k in EvidenceKind])
    size = serializers.IntegerField(min_value=1, max_value=MAX_BYTES)
    mime = serializers.ChoiceField(choices=sorted(ALLOWED_TYPES))
    sha256 = serializers.RegexField(HEX64)


class SubmissionItemSerializer(StrictSerializer):
    """One polling-unit result, captured offline and synced later (spec section 10).

    `payload_hash` is the SHA-256 (hex) of this object without `payload_hash`, serialized as
    canonical JSON: keys sorted at every level, no whitespace, UTF-8, values exactly as sent.
    """

    version_id = serializers.UUIDField()
    contest_id = serializers.UUIDField()
    polling_unit_id = serializers.UUIDField()
    config_version = serializers.IntegerField(min_value=1)
    parent_version_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    totals = TotalsSerializer()
    # DRF >= 3.14 enforces min/max_length on many=True; the type stubs predate it.
    votes = VoteLineSerializer(many=True, max_length=100)  # type: ignore[call-arg]
    device_captured_at = serializers.DateTimeField()
    gps = GpsSerializer(required=False, allow_null=True, default=None)
    device_id = serializers.UUIDField()
    app_version = serializers.CharField(max_length=32)
    payload_hash = serializers.RegexField(HEX64)
    evidence = EvidenceManifestSerializer(  # type: ignore[call-arg]
        many=True, max_length=5, required=False, default=list
    )


class SubmissionBatchSerializer(StrictSerializer):
    # Items are validated one by one so a malformed item doesn't sink the rest of the batch.
    items = serializers.ListField(child=serializers.DictField(), min_length=1, max_length=10)


class EvidenceUploadSchemaSerializer(serializers.Serializer):
    method = serializers.CharField()
    url = serializers.CharField()
    headers = serializers.DictField(child=serializers.CharField())
    expires_in = serializers.IntegerField()


class EvidenceUploadEntrySerializer(serializers.Serializer):
    evidence_id = serializers.UUIDField()
    status = serializers.CharField()
    upload = EvidenceUploadSchemaSerializer(required=False)


class SubmissionOutcomeSerializer(serializers.Serializer):
    version_id = serializers.UUIDField(allow_null=True)
    status = serializers.ChoiceField(choices=["SYNCED", "REQUIRES_REVIEW", "FAILED"])
    http_status = serializers.IntegerField()
    replayed = serializers.BooleanField()
    code = serializers.CharField(required=False)
    detail = serializers.CharField(required=False)
    version_no = serializers.IntegerField(required=False)
    state = serializers.CharField(required=False)
    is_head = serializers.BooleanField(required=False)
    flags = serializers.ListField(child=serializers.CharField(), required=False)
    evidence_uploads = EvidenceUploadEntrySerializer(many=True, required=False)

    def get_fields(self) -> dict[str, serializers.Field]:
        # Declared here, not as a class attribute: `errors` would shadow Serializer.errors.
        fields = super().get_fields()
        fields["errors"] = serializers.JSONField(required=False)
        return fields


class SubmissionResultSerializer(serializers.Serializer):
    items = SubmissionOutcomeSerializer(many=True)


class EvidenceStatusSerializer(serializers.Serializer):
    evidence_id = serializers.UUIDField()
    status = serializers.CharField()


class SyncStatusSerializer(serializers.Serializer):
    version_id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=["SYNCED", "REQUIRES_REVIEW", "UNKNOWN"])
    state = serializers.CharField(required=False)
    version_no = serializers.IntegerField(required=False)
    is_head = serializers.BooleanField(required=False)
    server_received_at = serializers.DateTimeField(required=False)
    evidence = EvidenceStatusSerializer(many=True, required=False)
