from rest_framework import serializers

from apps.core.api.serializers import StrictSerializer
from apps.reports.domain.formats import ExportFormat, ExportKind


class ExportRequestSerializer(StrictSerializer):
    kind = serializers.ChoiceField(choices=[k.value for k in ExportKind])
    format = serializers.ChoiceField(choices=[f.value for f in ExportFormat])
    election_id = serializers.UUIDField(required=False)
    contest_id = serializers.UUIDField(required=False)
    # Results: the level to export, the measure, and an LGA to narrow to.
    level = serializers.ChoiceField(choices=["pu", "ward", "lga"], required=False)
    measure = serializers.ChoiceField(choices=["reported", "verified"], required=False)
    parent_id = serializers.UUIDField(required=False)
    # Flags
    status = serializers.CharField(max_length=16, required=False)
    severity = serializers.CharField(max_length=10, required=False)
    rule_code = serializers.CharField(max_length=40, required=False)
    # Audit
    since = serializers.DateTimeField(required=False)
    until = serializers.DateTimeField(required=False)
    action = serializers.CharField(max_length=100, required=False)
    # Evidence packs
    lga_id = serializers.UUIDField(required=False)
    ward_id = serializers.UUIDField(required=False)
    polling_unit_id = serializers.UUIDField(required=False)


class ExportJobSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    kind = serializers.CharField()
    format = serializers.CharField()
    status = serializers.CharField()
    params = serializers.DictField()
    filename = serializers.CharField()
    size = serializers.IntegerField(allow_null=True)
    sha256 = serializers.CharField()
    manifest_sha256 = serializers.CharField()
    row_count = serializers.IntegerField(allow_null=True)
    file_count = serializers.IntegerField(allow_null=True)
    error = serializers.CharField()
    requested_by_id = serializers.UUIDField()
    requested_at = serializers.DateTimeField()
    finished_at = serializers.DateTimeField(allow_null=True)
    expires_at = serializers.DateTimeField(allow_null=True)
    download_count = serializers.IntegerField()


class DownloadSerializer(serializers.Serializer):
    url = serializers.CharField()
    expires_in = serializers.IntegerField()
    sha256 = serializers.CharField()
    size = serializers.IntegerField(allow_null=True)
