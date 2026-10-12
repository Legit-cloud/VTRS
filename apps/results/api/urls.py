from django.urls import path

from . import views

urlpatterns = [
    path("sync/submissions", views.SyncSubmissionsView.as_view(), name="sync-submissions"),
    path("sync/status", views.SyncStatusView.as_view(), name="sync-status"),
    path("results/<uuid:version_id>/review", views.ReviewView.as_view(), name="result-review"),
    path(
        "elections/<uuid:election_id>/review-queue",
        views.ReviewQueueView.as_view(),
        name="review-queue",
    ),
    path(
        "contests/<uuid:contest_id>/polling-units/<uuid:polling_unit_id>/history",
        views.PuHistoryView.as_view(),
        name="pu-history",
    ),
]
