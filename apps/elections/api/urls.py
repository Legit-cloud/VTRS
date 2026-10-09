from django.urls import path

from . import views

urlpatterns = [
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
        "elections/<uuid:election_id>/contests",
        views.ContestListView.as_view(),
        name="election-contests",
    ),
    path("contests/<uuid:contest_id>", views.ContestDetailView.as_view(), name="contest-detail"),
    path(
        "contests/<uuid:contest_id>/candidates",
        views.CandidateListView.as_view(),
        name="contest-candidates",
    ),
    path(
        "candidates/<uuid:candidate_id>",
        views.CandidateDetailView.as_view(),
        name="candidate-detail",
    ),
]
