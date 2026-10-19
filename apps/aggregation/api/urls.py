from django.urls import path

from . import views

urlpatterns = [
    path(
        "elections/<uuid:election_id>/dashboard",
        views.DashboardView.as_view(),
        name="election-dashboard",
    ),
    path(
        "elections/<uuid:election_id>/reconciliation",
        views.ReconciliationView.as_view(),
        name="election-reconciliation",
    ),
    path(
        "elections/<uuid:election_id>/reconcile",
        views.ElectionReconcileView.as_view(),
        name="election-reconcile",
    ),
    path(
        "elections/<uuid:election_id>/results",
        views.ElectionResultsView.as_view(),
        name="election-results",
    ),
    path(
        "elections/<uuid:election_id>/coverage-timeline",
        views.CoverageTimelineView.as_view(),
        name="election-coverage-timeline",
    ),
]
