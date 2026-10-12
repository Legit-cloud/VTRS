from uuid import UUID

from django.db.models import QuerySet
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView

from apps.core.api.views import StrictQueryParamsMixin
from apps.core.domain.permissions import Perm
from apps.core.pagination import KeysetPagination
from apps.geography import selectors
from apps.geography.models import Lga, PollingUnit, Ward

from .serializers import LgaSerializer, PollingUnitSerializer, WardSerializer

MAX_IDS = 100


class ByCodePagination(KeysetPagination):
    ordering = "inec_code"


class LgaListView(StrictQueryParamsMixin, ListAPIView):
    required_permission = Perm.GEOGRAPHY_VIEW
    serializer_class = LgaSerializer
    pagination_class = ByCodePagination
    allowed_query_params = frozenset({"state"})

    def get_queryset(self) -> QuerySet[Lga]:
        return selectors.lgas_for(self.actor, state_code=self.request.query_params.get("state"))


class WardListView(StrictQueryParamsMixin, ListAPIView):
    required_permission = Perm.GEOGRAPHY_VIEW
    serializer_class = WardSerializer
    pagination_class = ByCodePagination
    allowed_query_params = frozenset({"lga"})

    def get_queryset(self) -> QuerySet[Ward]:
        return selectors.wards_for(self.actor, lga_id=self.uuid_param("lga"))


class PollingUnitListView(StrictQueryParamsMixin, ListAPIView):
    required_permission = Perm.GEOGRAPHY_VIEW
    serializer_class = PollingUnitSerializer
    pagination_class = ByCodePagination
    allowed_query_params = frozenset({"ward", "lga", "ids"})

    def get_queryset(self) -> QuerySet[PollingUnit]:
        qs = selectors.polling_units_for(
            self.actor, ward_id=self.uuid_param("ward"), lga_id=self.uuid_param("lga")
        )
        # A comma-separated list, for looking up the few units a person is tied to by name.
        if raw := self.request.query_params.get("ids"):
            parts = [p.strip() for p in raw.split(",") if p.strip()]
            if len(parts) > MAX_IDS:
                raise ValidationError({"ids": [f"Give at most {MAX_IDS} ids."]})
            try:
                qs = qs.filter(id__in=[UUID(p) for p in parts])
            except ValueError:
                raise ValidationError(
                    {"ids": ["Must be a comma-separated list of UUIDs."]}
                ) from None
        return qs
