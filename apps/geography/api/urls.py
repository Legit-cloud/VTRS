from django.urls import path

from .views import (
    ConstituencyListView,
    ElectionTypeListView,
    LgaListView,
    PollingUnitListView,
    WardListView,
)

urlpatterns = [
    path("lgas", LgaListView.as_view(), name="geography-lgas"),
    path("wards", WardListView.as_view(), name="geography-wards"),
    path("polling-units", PollingUnitListView.as_view(), name="geography-polling-units"),
    path("election-types", ElectionTypeListView.as_view(), name="geography-election-types"),
    path("constituencies", ConstituencyListView.as_view(), name="geography-constituencies"),
]
