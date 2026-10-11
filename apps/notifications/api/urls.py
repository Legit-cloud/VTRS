from django.urls import path

from . import views

urlpatterns = [
    path("me/notifications", views.NotificationListView.as_view(), name="my-notifications"),
    path(
        "me/notifications/unread-count",
        views.UnreadCountView.as_view(),
        name="my-notifications-unread",
    ),
    path(
        "me/notifications/read-all",
        views.MarkAllReadView.as_view(),
        name="my-notifications-read-all",
    ),
    path(
        "me/notifications/<uuid:notification_id>/read",
        views.MarkReadView.as_view(),
        name="my-notification-read",
    ),
    path("me/push-token", views.PushTokenView.as_view(), name="my-push-token"),
]
