from django.urls import path

from . import views

urlpatterns = [
    path("sync/submissions", views.SyncSubmissionsView.as_view(), name="sync-submissions"),
    path("sync/status", views.SyncStatusView.as_view(), name="sync-status"),
]
