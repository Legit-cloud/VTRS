from rest_framework import serializers

from apps.geography.models import Lga, PollingUnit, Ward


class LgaSerializer(serializers.ModelSerializer):
    state_code = serializers.CharField(source="state.inec_code", read_only=True)

    class Meta:
        model = Lga
        fields = ("id", "inec_code", "name", "state_code")


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
            "latitude",
            "longitude",
            "registered_voters",
        )
