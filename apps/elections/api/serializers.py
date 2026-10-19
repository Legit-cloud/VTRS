from typing import Any

from rest_framework import serializers

from apps.core.api.serializers import StrictSerializer
from apps.elections import selectors, services
from apps.elections.domain.rules import ElectionStatus, IssueKind
from apps.elections.models import Candidate, ConfigIssue, CountPolicy, Election, Party

HEX64 = r"^[0-9a-fA-F]{64}$"


class PartySerializer(serializers.ModelSerializer):
    logo_url = serializers.SerializerMethodField()

    class Meta:
        model = Party
        fields = ("id", "full_name", "abbreviation", "is_own", "logo_url", "row_version")

    def get_logo_url(self, party: Party) -> str | None:
        return selectors.logo_url(party)


class PartyCreateSerializer(StrictSerializer):
    full_name = serializers.CharField(max_length=200)
    abbreviation = serializers.RegexField(r"^\s*[A-Za-z0-9-]{1,20}\s*$")
    is_own = serializers.BooleanField(default=False)


class PartyUpdateSerializer(StrictSerializer):
    full_name = serializers.CharField(max_length=200, required=False)
    abbreviation = serializers.RegexField(r"^\s*[A-Za-z0-9-]{1,20}\s*$", required=False)
    is_own = serializers.BooleanField(required=False)


class LogoUploadRequestSerializer(StrictSerializer):
    mime = serializers.ChoiceField(choices=sorted(services.LOGO_TYPES))
    size = serializers.IntegerField(min_value=1, max_value=services.LOGO_MAX_BYTES)
    sha256 = serializers.RegexField(HEX64)


class LogoUploadCompleteSerializer(StrictSerializer):
    mime = serializers.ChoiceField(choices=sorted(services.LOGO_TYPES))
    sha256 = serializers.RegexField(HEX64)


class UploadSerializer(serializers.Serializer):
    method = serializers.CharField()
    url = serializers.CharField()
    headers = serializers.DictField(child=serializers.CharField())
    expires_in = serializers.IntegerField()


class LogoUploadSerializer(serializers.Serializer):
    mime = serializers.CharField()
    sha256 = serializers.CharField()
    upload = UploadSerializer()


class ElectionSerializer(serializers.ModelSerializer):
    state_id = serializers.UUIDField()
    election_type = serializers.CharField(source="election_type.code")
    election_type_name = serializers.CharField(source="election_type.name")
    constituency_kind = serializers.CharField(source="election_type.constituency_kind")

    class Meta:
        model = Election
        fields = (
            "id",
            "name",
            "election_type",
            "election_type_name",
            "constituency_kind",
            "state_id",
            "election_date",
            "status",
            "count_policy",
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
    election_type = serializers.CharField(max_length=40)
    state_id = serializers.UUIDField()
    election_date = serializers.DateField()
    count_policy = serializers.ChoiceField(choices=CountPolicy.choices, default="REPORTED")
    polls_open_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    polls_close_at = serializers.DateTimeField(required=False, allow_null=True, default=None)


class ElectionUpdateSerializer(StrictSerializer):
    name = serializers.CharField(max_length=200, required=False)
    election_type = serializers.CharField(max_length=40, required=False)
    election_date = serializers.DateField(required=False)
    count_policy = serializers.ChoiceField(choices=CountPolicy.choices, required=False)
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


class ElectionPartySerializer(serializers.Serializer):
    party_id = serializers.UUIDField()
    ballot_order = serializers.IntegerField()
    abbreviation = serializers.CharField()
    full_name = serializers.CharField()
    is_own = serializers.BooleanField()
    logo_url = serializers.CharField(allow_null=True)

    @staticmethod
    def row(entry: Any) -> dict[str, Any]:
        return {
            "party_id": entry.party_id,
            "ballot_order": entry.ballot_order,
            "abbreviation": entry.party.abbreviation,
            "full_name": entry.party.full_name,
            "is_own": entry.party.is_own,
            "logo_url": selectors.logo_url(entry.party),
        }


class ElectionPartiesUpdateSerializer(StrictSerializer):
    # DRF >= 3.14 enforces max_length on ListField; the type stubs predate it.
    party_ids = serializers.ListField(child=serializers.UUIDField(), max_length=60)


class ContestantSerializer(serializers.ModelSerializer):
    contest_id = serializers.UUIDField(read_only=True)
    constituency_id = serializers.UUIDField(source="contest.constituency_id", read_only=True)
    constituency_name = serializers.CharField(source="contest.constituency.name", read_only=True)
    party_id = serializers.UUIDField(read_only=True)
    party_abbreviation = serializers.CharField(source="party.abbreviation", read_only=True)
    ballot_order = serializers.IntegerField(read_only=True, allow_null=True)

    class Meta:
        model = Candidate
        fields = (
            "id",
            "contest_id",
            "constituency_id",
            "constituency_name",
            "party_id",
            "party_abbreviation",
            "ballot_order",
            "name",
            "config_version",
            "row_version",
        )


class ContestantCreateSerializer(StrictSerializer):
    constituency_id = serializers.UUIDField()
    party_id = serializers.UUIDField()
    name = serializers.CharField(max_length=200)


class ContestantUpdateSerializer(StrictSerializer):
    name = serializers.CharField(max_length=200)


class ConfigIssueSerializer(serializers.ModelSerializer):
    election_id = serializers.UUIDField(read_only=True)
    polling_unit_id = serializers.UUIDField(read_only=True)
    polling_unit_code = serializers.CharField(source="polling_unit.inec_code", read_only=True)
    polling_unit_name = serializers.CharField(source="polling_unit.name", read_only=True)
    ward_name = serializers.CharField(source="ward.name", read_only=True)
    lga_name = serializers.CharField(source="lga.name", read_only=True)
    raised_by_name = serializers.CharField(source="raised_by.full_name", read_only=True)
    resolved_by_name = serializers.SerializerMethodField()

    class Meta:
        model = ConfigIssue
        fields = (
            "id",
            "election_id",
            "polling_unit_id",
            "polling_unit_code",
            "polling_unit_name",
            "ward_name",
            "lga_name",
            "kind",
            "note",
            "status",
            "raised_by_name",
            "created_at",
            "resolution_note",
            "resolved_by_name",
            "resolved_at",
        )

    def get_resolved_by_name(self, issue: ConfigIssue) -> str | None:
        return issue.resolved_by.full_name if issue.resolved_by else None


class ConfigIssueCreateSerializer(StrictSerializer):
    polling_unit_id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=[k.value for k in IssueKind])
    note = serializers.CharField(min_length=3, max_length=500)


class ConfigIssueResolveSerializer(StrictSerializer):
    note = serializers.CharField(min_length=3, max_length=500)
