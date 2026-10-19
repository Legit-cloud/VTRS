from django.urls import path

from . import views

urlpatterns = [
    path("parties", views.PartyListView.as_view(), name="parties"),
    path("parties/<uuid:party_id>", views.PartyDetailView.as_view(), name="party-detail"),
    path("parties/<uuid:party_id>/logo", views.PartyLogoView.as_view(), name="party-logo"),
    path(
        "parties/<uuid:party_id>/logo/complete",
        views.PartyLogoCompleteView.as_view(),
        name="party-logo-complete",
    ),
    path("elections", views.ElectionListView.as_view(), name="elections"),
    path(
        "elections/<uuid:election_id>", views.ElectionDetailView.as_view(), name="election-detail"
    ),
    path(
        "elections/<uuid:election_id>/lock", views.ElectionLockView.as_view(), name="election-lock"
    ),
    path(
        "elections/<uuid:election_id>/transition",
        views.ElectionTransitionView.as_view(),
        name="election-transition",
    ),
    path(
        "elections/<uuid:election_id>/parties",
        views.ElectionPartiesView.as_view(),
        name="election-parties",
    ),
    path(
        "elections/<uuid:election_id>/contestants",
        views.ContestantListView.as_view(),
        name="election-contestants",
    ),
    path(
        "contestants/<uuid:candidate_id>",
        views.ContestantDetailView.as_view(),
        name="contestant-detail",
    ),
    path(
        "config-issues/<uuid:issue_id>/resolve",
        views.ConfigIssueResolveView.as_view(),
        name="config-issue-resolve",
    ),
]
