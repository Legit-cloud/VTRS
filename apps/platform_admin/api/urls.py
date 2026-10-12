from django.urls import path

from . import views

urlpatterns = [
    path("platform/overview", views.OverviewView.as_view(), name="platform-overview"),
    path("platform/organizations", views.OrganizationListView.as_view(), name="platform-orgs"),
    path(
        "platform/verification-queue",
        views.VerificationQueueView.as_view(),
        name="platform-verification-queue",
    ),
    path(
        "platform/organizations/<uuid:organization_id>",
        views.OrganizationDetailView.as_view(),
        name="platform-org-detail",
    ),
    path(
        "platform/organizations/<uuid:organization_id>/approve",
        views.ApproveView.as_view(),
        name="platform-org-approve",
    ),
    path(
        "platform/organizations/<uuid:organization_id>/reject",
        views.RejectView.as_view(),
        name="platform-org-reject",
    ),
    path(
        "platform/organizations/<uuid:organization_id>/suspend",
        views.SuspendView.as_view(),
        name="platform-org-suspend",
    ),
    path(
        "platform/organizations/<uuid:organization_id>/reinstate",
        views.ReinstateView.as_view(),
        name="platform-org-reinstate",
    ),
    path("platform/elections", views.ElectionListView.as_view(), name="platform-elections"),
    path("platform/master-data", views.MasterDataView.as_view(), name="platform-master-data"),
    path(
        "platform/master-data/search",
        views.MasterDataSearchView.as_view(),
        name="platform-master-data-search",
    ),
    path(
        "platform/master-data/preview",
        views.MasterDataPreviewView.as_view(),
        name="platform-master-data-preview",
    ),
    path(
        "platform/master-data/import",
        views.MasterDataImportView.as_view(),
        name="platform-master-data-import",
    ),
    path("platform/messaging", views.MessagingView.as_view(), name="platform-messaging"),
    path(
        "platform/messaging/test", views.MessagingTestView.as_view(), name="platform-messaging-test"
    ),
    path("platform/audit", views.AuditListView.as_view(), name="platform-audit"),
]
