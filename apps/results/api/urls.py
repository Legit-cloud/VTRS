from django.urls import path

from . import views

urlpatterns = [
    path("me/assignments", views.MyAssignmentsView.as_view(), name="my-assignments"),
    path(
        "elections/<uuid:election_id>/polling-units/<uuid:polling_unit_id>/form",
        views.ResultFormView.as_view(),
        name="result-form",
    ),
    path("submissions", views.SubmissionView.as_view(), name="submissions"),
    path(
        "submissions/<uuid:version_id>",
        views.SubmissionStatusView.as_view(),
        name="submission-status",
    ),
    path(
        "elections/<uuid:election_id>/config-issues",
        views.ConfigIssuesView.as_view(),
        name="election-config-issues",
    ),
    path("results/<uuid:version_id>/review", views.ReviewView.as_view(), name="result-review"),
    path(
        "elections/<uuid:election_id>/review-queue",
        views.ReviewQueueView.as_view(),
        name="review-queue",
    ),
    path(
        "elections/<uuid:election_id>/polling-units/<uuid:polling_unit_id>/history",
        views.PuHistoryView.as_view(),
        name="pu-history",
    ),
]
