from rest_framework import serializers

from apps.core.api.serializers import StrictSerializer
from apps.evidence.domain.rules import ALLOWED_TYPES, MAX_BYTES, EvidenceKind
from apps.results.domain.versions import ReviewDecision

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
    review = serializers.JSONField(required=False, allow_null=True)


class ReviewRequestSerializer(StrictSerializer):
    decision = serializers.ChoiceField(choices=[d.value for d in ReviewDecision])
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    acknowledge_flags = serializers.BooleanField(required=False, default=False)


class ReviewOutcomeSerializer(serializers.Serializer):
    version_id = serializers.UUIDField()
    decision = serializers.CharField()
    state = serializers.CharField()
    head_version_id = serializers.UUIDField(allow_null=True)
    pu_status = serializers.CharField()
    decided_at = serializers.DateTimeField()


class VoteView(serializers.Serializer):
    candidate_id = serializers.UUIDField()
    party_acronym = serializers.CharField()
    name = serializers.CharField()
    votes = serializers.IntegerField()


class FlagView(serializers.Serializer):
    id = serializers.UUIDField()
    rule_code = serializers.CharField()
    severity = serializers.CharField()
    status = serializers.CharField()


class PersonView(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class TotalsView(serializers.Serializer):
    accredited = serializers.IntegerField(allow_null=True)
    valid = serializers.IntegerField()
    rejected = serializers.IntegerField(allow_null=True)
    total_cast = serializers.IntegerField(allow_null=True)


class ReviewQueueItemSerializer(serializers.Serializer):
    version_id = serializers.UUIDField()
    contest_id = serializers.UUIDField()
    contest_title = serializers.CharField()
    polling_unit_id = serializers.UUIDField()
    polling_unit_code = serializers.CharField()
    polling_unit_name = serializers.CharField()
    ward_id = serializers.UUIDField()
    ward_name = serializers.CharField()
    lga_id = serializers.UUIDField()
    lga_name = serializers.CharField()
    version_no = serializers.IntegerField()
    state = serializers.CharField()
    totals = TotalsView()
    votes = VoteView(many=True)
    flags = FlagView(many=True)
    submitted_by = PersonView()
    server_received_at = serializers.DateTimeField()


class ReviewEntryView(serializers.Serializer):
    decision = serializers.CharField()
    from_state = serializers.CharField()
    reason = serializers.CharField()
    acknowledged_flags = serializers.ListField(child=serializers.CharField())
    decided_by = PersonView()
    decided_at = serializers.DateTimeField()


class EvidenceView(serializers.Serializer):
    evidence_id = serializers.UUIDField()
    kind = serializers.CharField()
    status = serializers.CharField()
    sha256 = serializers.CharField()


class GpsView(serializers.Serializer):
    lat = serializers.DecimalField(max_digits=9, decimal_places=6)
    lng = serializers.DecimalField(max_digits=9, decimal_places=6)
    accuracy_m = serializers.DecimalField(max_digits=8, decimal_places=2, allow_null=True)


class HistoryVersionSerializer(serializers.Serializer):
    version_id = serializers.UUIDField()
    version_no = serializers.IntegerField()
    state = serializers.CharField()
    is_head = serializers.BooleanField()
    parent_version_id = serializers.UUIDField(allow_null=True)
    totals = TotalsView()
    votes = VoteView(many=True)
    flags = FlagView(many=True)
    reviews = ReviewEntryView(many=True)
    evidence_count = serializers.IntegerField()
    evidence = EvidenceView(many=True, required=False)
    submitted_by = PersonView()
    device_captured_at = serializers.DateTimeField()
    server_received_at = serializers.DateTimeField()
    gps = GpsView(allow_null=True)
    payload_hash = serializers.CharField()


class PuHistorySerializer(serializers.Serializer):
    contest_id = serializers.UUIDField()
    polling_unit_id = serializers.UUIDField()
    polling_unit_code = serializers.CharField()
    polling_unit_name = serializers.CharField()
    ward_id = serializers.UUIDField()
    lga_id = serializers.UUIDField()
    status = serializers.CharField()
    head_version_id = serializers.UUIDField(allow_null=True)
    versions = HistoryVersionSerializer(many=True)
