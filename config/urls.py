from django.urls import include, path

urlpatterns = [
    path("api/v1/", include("apps.core.api.urls")),
    path("api/v1/geography/", include("apps.geography.api.urls")),
]
