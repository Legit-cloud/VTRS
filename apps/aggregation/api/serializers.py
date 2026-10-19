from rest_framework import serializers


class PartyVoteSerializer(serializers.Serializer):
    party_id = serializers.UUIDField()
    abbreviation = serializers.CharField()
    # Set when the area is a single constituency, where each party has one contestant.
    candidate_id = serializers.UUIDField(allow_null=True)
    candidate_name = serializers.CharField(allow_null=True)
    votes = serializers.IntegerField()


class TotalsSerializer(serializers.Serializer):
    accredited = serializers.IntegerField(allow_null=True)
    valid = serializers.IntegerField(allow_null=True)
    rejected = serializers.IntegerField(allow_null=True)
    total_cast = serializers.IntegerField(allow_null=True)


class PositionSerializer(serializers.Serializer):
    """The provisional position. `status` is NO_VOTES, TIED, NARROW or LEADING; a tie names no
    leader (`leading_party_ids` lists every party sharing the top)."""

    status = serializers.ChoiceField(choices=["NO_VOTES", "TIED", "NARROW", "LEADING"])
    leader_party_id = serializers.UUIDField(allow_null=True)
    leader_abbreviation = serializers.CharField(allow_null=True)
    runner_up_party_id = serializers.UUIDField(allow_null=True)
    leading_party_ids = serializers.ListField(child=serializers.UUIDField())
    margin = serializers.IntegerField()
    margin_pct = serializers.FloatField(allow_null=True)
    total_votes = serializers.IntegerField()
    is_tie = serializers.BooleanField()
    own_margin = serializers.IntegerField(allow_null=True)


class AreaResultSerializer(serializers.Serializer):
    """One area's figures. `votes` and `totals` follow `measure`; the polling-unit counts for
    both measures are always present, so "X of Y reported" travels with every total."""

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
    votes = PartyVoteSerializer(many=True)
    position = PositionSerializer()
    measure = serializers.CharField()
    updated_at = serializers.DateTimeField(allow_null=True)
    # Polling-unit rows only.
    status = serializers.CharField(required=False)
    head_version_id = serializers.UUIDField(required=False, allow_null=True)
    verified = serializers.BooleanField(required=False)
    completion = serializers.CharField(required=False, allow_null=True)


class BallotPartySerializer(serializers.Serializer):
    party_id = serializers.UUIDField()
    abbreviation = serializers.CharField()
    full_name = serializers.CharField()
    ballot_order = serializers.IntegerField()
    is_own = serializers.BooleanField()
    logo_url = serializers.CharField(allow_null=True)


class _ElectionHeaderSerializer(serializers.Serializer):
    election_id = serializers.UUIDField()
    election_name = serializers.CharField()
    election_type = serializers.CharField()
    election_type_name = serializers.CharField()
    status = serializers.CharField()
    measure = serializers.CharField()
    provisional = serializers.BooleanField()
    notice = serializers.CharField()
    parties = BallotPartySerializer(many=True)


class DashboardSerializer(_ElectionHeaderSerializer):
    summary = AreaResultSerializer()
    areas_in_scope = serializers.IntegerField()


class ElectionResultsSerializer(_ElectionHeaderSerializer):
    level = serializers.CharField()
    parent_id = serializers.UUIDField(allow_null=True)
    rows = AreaResultSerializer(many=True)


class TimelinePointSerializer(serializers.Serializer):
    at = serializers.DateTimeField()
    newly_reported = serializers.IntegerField()
    cumulative = serializers.IntegerField()


class CoverageTimelineSerializer(serializers.Serializer):
    election_id = serializers.UUIDField()
    interval = serializers.CharField()
    expected_pus = serializers.IntegerField()
    points = TimelinePointSerializer(many=True)


class ReadinessSerializer(serializers.Serializer):
    election_id = serializers.UUIDField()
    status = serializers.CharField()
    unverified_results = serializers.IntegerField()
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
