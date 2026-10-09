from django.urls import path

from .views import LiveView, ReadyView, ServerTimeView

urlpatterns = [
    path("health/live", LiveView.as_view(), name="health-live"),
    path("health/ready", ReadyView.as_view(), name="health-ready"),
    path("time", ServerTimeView.as_view(), name="server-time"),
]
