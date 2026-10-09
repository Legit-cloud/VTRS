from django.urls import path

from . import views

urlpatterns = [
    path("assignments", views.AssignmentListView.as_view(), name="assignments"),
    path(
        "assignments/<uuid:assignment_id>/revoke",
        views.AssignmentRevokeView.as_view(),
        name="assignment-revoke",
    ),
    path("me/assignments", views.MyAssignmentsView.as_view(), name="my-assignments"),
]
