from django.conf import settings
from django.urls import URLPattern, URLResolver, include, path

urlpatterns: list[URLPattern | URLResolver] = [
    path("api/v1/", include("apps.core.api.urls")),
    path("api/v1/", include("apps.accounts.api.urls")),
    path("api/v1/geography/", include("apps.geography.api.urls")),
]

if settings.VTRS_EXPOSE_SCHEMA:
    from apps.core.api.views import SchemaView

    urlpatterns.append(path("api/v1/schema", SchemaView.as_view(), name="schema"))
