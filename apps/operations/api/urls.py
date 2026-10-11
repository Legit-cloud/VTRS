from django.urls import path

from . import views

urlpatterns = [
    path("admin/health", views.SystemHealthView.as_view(), name="admin-health"),
    path("admin/data-quality", views.DataQualityView.as_view(), name="admin-data-quality"),
    path(
        "elections/<uuid:election_id>/analytics",
        views.AnalyticsView.as_view(),
        name="election-analytics",
    ),
]
