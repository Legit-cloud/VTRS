from django.db.models import QuerySet
from rest_framework.generics import ListAPIView

from apps.core.api.views import StrictQueryParamsMixin
from apps.core.domain.permissions import Perm
from apps.core.pagination import KeysetPagination
from apps.geography import selectors
from apps.geography.models import Lga, PollingUnit, Ward

from .serializers import LgaSerializer, PollingUnitSerializer, WardSerializer


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
    allowed_query_params = frozenset({"ward", "lga"})

    def get_queryset(self) -> QuerySet[PollingUnit]:
        return selectors.polling_units_for(
            self.actor, ward_id=self.uuid_param("ward"), lga_id=self.uuid_param("lga")
        )
