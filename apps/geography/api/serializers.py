from rest_framework import serializers

from apps.geography.models import Constituency, ElectionType, Lga, PollingUnit, Ward


class LgaSerializer(serializers.ModelSerializer):
    state_code = serializers.CharField(source="state.inec_code", read_only=True)
    # Clients need the state's id to create an election; there is no states endpoint.
    state_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Lga
        fields = ("id", "inec_code", "name", "state_code", "state_id")


class WardSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ward
        fields = ("id", "inec_code", "name", "lga_id")


class PollingUnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = PollingUnit
        fields = (
            "id",
            "inec_code",
            "name",
            "ward_id",
            "lga_id",
            "state_id",
            "latitude",
            "longitude",
            "registered_voters",
        )


class ElectionTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ElectionType
        fields = ("code", "name", "constituency_kind")


class ConstituencySerializer(serializers.ModelSerializer):
    class Meta:
        model = Constituency
        fields = ("id", "kind", "code", "name", "state_id")
