from rest_framework import serializers

from apps.core.api.serializers import StrictSerializer
from apps.elections.domain.rules import SHEET_FIELDS, ElectionStatus, JurisdictionLevel
from apps.elections.models import Candidate, Contest, CountPolicy, Election, Office


class ElectionSerializer(serializers.ModelSerializer):
    state_id = serializers.UUIDField()

    class Meta:
        model = Election
        fields = (
            "id",
            "name",
            "state_id",
            "election_date",
            "status",
            "count_policy",
            "review_enabled",
            "polls_open_at",
            "polls_close_at",
            "config_version",
            "config_hash",
            "row_version",
            "locked_at",
            "opened_at",
            "closed_at",
            "created_at",
        )


class ElectionCreateSerializer(StrictSerializer):
    name = serializers.CharField(max_length=200)
    state_id = serializers.UUIDField()
    election_date = serializers.DateField()
    count_policy = serializers.ChoiceField(choices=CountPolicy.choices, default="REPORTED")
    review_enabled = serializers.BooleanField(default=False)
    polls_open_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    polls_close_at = serializers.DateTimeField(required=False, allow_null=True, default=None)


class ElectionUpdateSerializer(StrictSerializer):
    name = serializers.CharField(max_length=200, required=False)
    election_date = serializers.DateField(required=False)
    count_policy = serializers.ChoiceField(choices=CountPolicy.choices, required=False)
    review_enabled = serializers.BooleanField(required=False)
    polls_open_at = serializers.DateTimeField(required=False, allow_null=True)
    polls_close_at = serializers.DateTimeField(required=False, allow_null=True)


class TransitionSerializer(StrictSerializer):
    # LOCKED has its own endpoint (it needs a fresh second factor).
    to = serializers.ChoiceField(
        choices=[
            ElectionStatus.DRAFT.value,
            ElectionStatus.CONFIGURED.value,
            ElectionStatus.LIVE.value,
            ElectionStatus.CLOSED.value,
        ]
    )


class ContestSerializer(serializers.ModelSerializer):
    election_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Contest
        fields = (
            "id",
            "election_id",
            "office",
            "title",
            "jurisdiction_level",
            "jurisdiction_ids",
            "sheet_fields",
            "row_version",
            "created_at",
        )


_LEVELS = [level.value for level in JurisdictionLevel]


class ContestCreateSerializer(StrictSerializer):
    office = serializers.ChoiceField(choices=Office.choices)
    title = serializers.CharField(max_length=200)
    jurisdiction_level = serializers.ChoiceField(choices=_LEVELS)
    jurisdiction_ids = serializers.ListField(child=serializers.UUIDField(), max_length=400)
    sheet_fields = serializers.ListField(
        child=serializers.ChoiceField(choices=list(SHEET_FIELDS)),
        max_length=len(SHEET_FIELDS),
        default=lambda: list(SHEET_FIELDS),
    )


class ContestUpdateSerializer(StrictSerializer):
    office = serializers.ChoiceField(choices=Office.choices, required=False)
    title = serializers.CharField(max_length=200, required=False)
    jurisdiction_level = serializers.ChoiceField(choices=_LEVELS, required=False)
    jurisdiction_ids = serializers.ListField(
        child=serializers.UUIDField(), max_length=400, required=False
    )
    sheet_fields = serializers.ListField(
        child=serializers.ChoiceField(choices=list(SHEET_FIELDS)),
        max_length=len(SHEET_FIELDS),
        required=False,
    )


class CandidateSerializer(serializers.ModelSerializer):
    contest_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Candidate
        fields = (
            "id",
            "contest_id",
            "name",
            "party_name",
            "party_acronym",
            "ballot_order",
            "is_own_party",
            "config_version",
            "row_version",
        )


class CandidateCreateSerializer(StrictSerializer):
    name = serializers.CharField(max_length=200)
    party_name = serializers.CharField(max_length=200)
    party_acronym = serializers.RegexField(r"^[A-Za-z0-9-]{1,20}$")
    ballot_order = serializers.IntegerField(min_value=1, max_value=200)
    is_own_party = serializers.BooleanField(default=False)


class CandidateUpdateSerializer(StrictSerializer):
    name = serializers.CharField(max_length=200, required=False)
    party_name = serializers.CharField(max_length=200, required=False)
    party_acronym = serializers.RegexField(r"^[A-Za-z0-9-]{1,20}$", required=False)
    ballot_order = serializers.IntegerField(min_value=1, max_value=200, required=False)
    is_own_party = serializers.BooleanField(required=False)
