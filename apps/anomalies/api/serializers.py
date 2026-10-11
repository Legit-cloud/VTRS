from rest_framework import serializers

from apps.anomalies.models import FlagStatus
from apps.core.api.serializers import StrictSerializer


class FlagSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    election_id = serializers.UUIDField()
    contest_id = serializers.UUIDField(allow_null=True)
    polling_unit_id = serializers.UUIDField()
    polling_unit_code = serializers.CharField()
    polling_unit_name = serializers.CharField()
    ward_id = serializers.UUIDField()
    ward_name = serializers.CharField()
    lga_id = serializers.UUIDField()
    lga_name = serializers.CharField()
    result_version_id = serializers.UUIDField(allow_null=True)
    rule_code = serializers.CharField()
    title = serializers.CharField()
    severity = serializers.CharField()
    status = serializers.CharField()
    details = serializers.DictField()
    escalation_level = serializers.IntegerField()
    sla_due_at = serializers.DateTimeField(allow_null=True)
    assigned_to_id = serializers.UUIDField(allow_null=True)
    acknowledged_at = serializers.DateTimeField(allow_null=True)
    resolved_at = serializers.DateTimeField(allow_null=True)
    resolution_note = serializers.CharField()
    created_at = serializers.DateTimeField()


class FlagEventSerializer(serializers.Serializer):
    action = serializers.CharField()
    from_status = serializers.CharField()
    to_status = serializers.CharField()
    actor_id = serializers.UUIDField(allow_null=True)
    note = serializers.CharField()
    details = serializers.DictField()
    at = serializers.DateTimeField()


class FlagDetailSerializer(FlagSerializer):
    events = FlagEventSerializer(many=True)


class FlagSummarySerializer(serializers.Serializer):
    election_id = serializers.UUIDField()
    by_status = serializers.DictField(child=serializers.IntegerField())
    active_by_severity = serializers.DictField(child=serializers.IntegerField())
    active_by_rule = serializers.DictField(child=serializers.IntegerField())
    escalated_open = serializers.IntegerField()
    unacknowledged_critical = serializers.IntegerField()
    closed = serializers.IntegerField()
    average_minutes_to_resolve = serializers.FloatField(allow_null=True)


class ResolveSerializer(StrictSerializer):
    outcome = serializers.ChoiceField(choices=[FlagStatus.RESOLVED, FlagStatus.FALSE_POSITIVE])
    note = serializers.CharField(min_length=3, max_length=1000)


class NoteSerializer(StrictSerializer):
    note = serializers.CharField(min_length=3, max_length=1000)


class AlertPolicyUpdateSerializer(StrictSerializer):
    matrix = serializers.DictField(child=serializers.DictField())


class AlertPolicySerializer(serializers.Serializer):
    overridden = serializers.BooleanField()
    override = serializers.DictField()
    effective = serializers.DictField()
    updated_at = serializers.DateTimeField(allow_null=True)


class AssignSerializer(StrictSerializer):
    assignee_id = serializers.UUIDField(allow_null=True)
