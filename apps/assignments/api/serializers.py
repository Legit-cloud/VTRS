from rest_framework import serializers

from apps.assignments.models import AgentAssignment
from apps.core.api.serializers import StrictSerializer


class AssignmentSerializer(serializers.ModelSerializer):
    election_id = serializers.UUIDField(read_only=True)
    agent_id = serializers.UUIDField(read_only=True)
    agent_name = serializers.CharField(source="agent.full_name", read_only=True)
    polling_unit_id = serializers.UUIDField(read_only=True)
    polling_unit_code = serializers.CharField(source="polling_unit.inec_code", read_only=True)
    ward_id = serializers.UUIDField(read_only=True)
    lga_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = AgentAssignment
        fields = (
            "id",
            "election_id",
            "agent_id",
            "agent_name",
            "polling_unit_id",
            "polling_unit_code",
            "ward_id",
            "lga_id",
            "status",
            "valid_from",
            "valid_to",
            "revoked_at",
            "created_at",
        )


class AssignmentCreateSerializer(StrictSerializer):
    election_id = serializers.UUIDField()
    agent_id = serializers.UUIDField()
    polling_unit_id = serializers.UUIDField()


class CandidateBallotSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    party_acronym = serializers.CharField()
    ballot_order = serializers.IntegerField()


class ContestBallotSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    office = serializers.CharField()
    title = serializers.CharField()
    sheet_fields = serializers.ListField(child=serializers.CharField())
    candidates = CandidateBallotSerializer(many=True)


class AssignedElectionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    election_date = serializers.DateField()
    status = serializers.CharField()
    capture_open = serializers.BooleanField()
    config_version = serializers.IntegerField()
    polls_open_at = serializers.DateTimeField(allow_null=True)
    polls_close_at = serializers.DateTimeField(allow_null=True)


class AssignedPollingUnitSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    inec_code = serializers.CharField()
    name = serializers.CharField()
    ward = serializers.CharField()
    lga = serializers.CharField()
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, allow_null=True)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, allow_null=True)
    registered_voters = serializers.IntegerField(allow_null=True)


class MyAssignmentSerializer(serializers.Serializer):
    assignment_id = serializers.UUIDField()
    election = AssignedElectionSerializer()
    polling_unit = AssignedPollingUnitSerializer()
    contests = ContestBallotSerializer(many=True)
