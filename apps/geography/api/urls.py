from django.urls import path

from .views import LgaListView, PollingUnitListView, WardListView

urlpatterns = [
    path("lgas", LgaListView.as_view(), name="geography-lgas"),
    path("wards", WardListView.as_view(), name="geography-wards"),
    path("polling-units", PollingUnitListView.as_view(), name="geography-polling-units"),
]
