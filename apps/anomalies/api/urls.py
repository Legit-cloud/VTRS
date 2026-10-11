from django.urls import path

from . import views

urlpatterns = [
    path("elections/<uuid:election_id>/flags", views.FlagListView.as_view(), name="election-flags"),
    path(
        "elections/<uuid:election_id>/flags/summary",
        views.FlagSummaryView.as_view(),
        name="election-flags-summary",
    ),
    path("flags/<uuid:flag_id>", views.FlagDetailView.as_view(), name="flag-detail"),
    path(
        "flags/<uuid:flag_id>/acknowledge",
        views.FlagAcknowledgeView.as_view(),
        name="flag-acknowledge",
    ),
    path("flags/<uuid:flag_id>/comments", views.FlagCommentView.as_view(), name="flag-comment"),
    path("flags/<uuid:flag_id>/assign", views.FlagAssignView.as_view(), name="flag-assign"),
    path("flags/<uuid:flag_id>/resolve", views.FlagResolveView.as_view(), name="flag-resolve"),
    path("flags/<uuid:flag_id>/reopen", views.FlagReopenView.as_view(), name="flag-reopen"),
]
