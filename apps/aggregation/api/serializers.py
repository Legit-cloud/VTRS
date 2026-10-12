from rest_framework import serializers


class VoteSerializer(serializers.Serializer):
    candidate_id = serializers.UUIDField()
    party_acronym = serializers.CharField()
    name = serializers.CharField()
    votes = serializers.IntegerField()


class TotalsSerializer(serializers.Serializer):
    accredited = serializers.IntegerField(allow_null=True)
    valid = serializers.IntegerField(allow_null=True)
    rejected = serializers.IntegerField(allow_null=True)
    total_cast = serializers.IntegerField(allow_null=True)


class PositionSerializer(serializers.Serializer):
    leader_id = serializers.UUIDField(allow_null=True)
    leader_party = serializers.CharField(allow_null=True)
    runner_up_id = serializers.UUIDField(allow_null=True)
    leading_ids = serializers.ListField(child=serializers.UUIDField())
    margin = serializers.IntegerField()
    margin_pct = serializers.FloatField(allow_null=True)
    total_votes = serializers.IntegerField()
    is_tie = serializers.BooleanField()
    own_margin = serializers.IntegerField(allow_null=True)


class AreaResultSerializer(serializers.Serializer):
    """One area's figures. `votes` and `totals` follow `measure`; the polling-unit counts
    for both measures are always present."""

    level = serializers.CharField()
    area_id = serializers.UUIDField()
    area_name = serializers.CharField()
    area_code = serializers.CharField()
    parent_id = serializers.UUIDField(allow_null=True)
    expected_pus = serializers.IntegerField()
    reported_pus = serializers.IntegerField()
    verified_pus = serializers.IntegerField()
    review_pus = serializers.IntegerField()
    reported_pct = serializers.FloatField()
    verified_pct = serializers.FloatField()
    counted_pus = serializers.IntegerField()
    open_flags = serializers.IntegerField()
    registered_voters = serializers.IntegerField()
    totals = TotalsSerializer()
    votes = VoteSerializer(many=True)
    position = PositionSerializer()
    measure = serializers.CharField()
    updated_at = serializers.DateTimeField(allow_null=True)
    revision = serializers.IntegerField(allow_null=True)
    # Polling-unit rows only.
    status = serializers.CharField(required=False)
    head_version_id = serializers.UUIDField(required=False, allow_null=True)


class ContestSummarySerializer(AreaResultSerializer):
    contest_id = serializers.UUIDField()
    office = serializers.CharField()
    title = serializers.CharField()
    areas_in_scope = serializers.IntegerField()


class DashboardSerializer(serializers.Serializer):
    election_id = serializers.UUIDField()
    election_name = serializers.CharField()
    status = serializers.CharField()
    measure = serializers.CharField()
    review_enabled = serializers.BooleanField()
    provisional = serializers.BooleanField()
    notice = serializers.CharField()
    contests = ContestSummarySerializer(many=True)


class ContestResultsSerializer(serializers.Serializer):
    contest_id = serializers.UUIDField()
    level = serializers.CharField()
    parent_id = serializers.UUIDField(allow_null=True)
    measure = serializers.CharField()
    provisional = serializers.BooleanField()
    notice = serializers.CharField()
    rows = AreaResultSerializer(many=True)


class TimelinePointSerializer(serializers.Serializer):
    at = serializers.DateTimeField()
    newly_reported = serializers.IntegerField()
    cumulative = serializers.IntegerField()


class CoverageTimelineSerializer(serializers.Serializer):
    contest_id = serializers.UUIDField()
    interval = serializers.CharField()
    expected_pus = serializers.IntegerField()
    points = TimelinePointSerializer(many=True)


class ReadinessSerializer(serializers.Serializer):
    election_id = serializers.UUIDField()
    status = serializers.CharField()
    review_enabled = serializers.BooleanField()
    undecided_results = serializers.IntegerField()
    rollup_differences = serializers.ListField(child=serializers.CharField())
    can_reconcile = serializers.BooleanField()
    reconciled_at = serializers.DateTimeField(allow_null=True)
    snapshot_sha256 = serializers.CharField(allow_null=True)


class ReconcileOutcomeSerializer(serializers.Serializer):
    election_id = serializers.UUIDField()
    status = serializers.CharField()
    snapshot_id = serializers.UUIDField()
    snapshot_sha256 = serializers.CharField()
    reported_pus = serializers.IntegerField()
    verified_pus = serializers.IntegerField()
    reconciled_at = serializers.DateTimeField()
