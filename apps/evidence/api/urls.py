from django.urls import path

from . import views

urlpatterns = [
    path("evidence/uploads", views.UploadRequestView.as_view(), name="evidence-uploads"),
    path(
        "evidence/<uuid:evidence_id>/complete",
        views.UploadCompleteView.as_view(),
        name="evidence-complete",
    ),
    path(
        "evidence/<uuid:evidence_id>/download-url",
        views.DownloadUrlView.as_view(),
        name="evidence-download-url",
    ),
]
