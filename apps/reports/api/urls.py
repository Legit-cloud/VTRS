from django.urls import path

from . import views

urlpatterns = [
    path("exports", views.ExportListView.as_view(), name="exports"),
    path("exports/<uuid:job_id>", views.ExportDetailView.as_view(), name="export-detail"),
    path(
        "exports/<uuid:job_id>/download-url",
        views.ExportDownloadView.as_view(),
        name="export-download-url",
    ),
]
