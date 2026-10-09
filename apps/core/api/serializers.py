from collections.abc import Mapping
from typing import Any

from rest_framework import serializers


class StrictSerializer(serializers.Serializer):
    """Rejects fields the serializer does not declare (spec section 9)."""

    def to_internal_value(self, data: Any) -> Any:
        if isinstance(data, Mapping):
            unknown = set(data) - set(self.fields)
            if unknown:
                raise serializers.ValidationError(
                    {name: ["Unknown field."] for name in sorted(unknown)}
                )
        return super().to_internal_value(data)
