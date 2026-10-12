from django.urls import path

from . import consumers

websocket_urlpatterns = [
    path("ws/v1/dashboard", consumers.DashboardConsumer.as_asgi()),
]
