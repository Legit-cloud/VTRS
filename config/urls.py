from django.conf import settings
from django.urls import URLPattern, URLResolver, include, path

urlpatterns: list[URLPattern | URLResolver] = [
    path("api/v1/", include("apps.core.api.urls")),
    path("api/v1/", include("apps.accounts.api.urls")),
    path("api/v1/", include("apps.elections.api.urls")),
    path("api/v1/", include("apps.assignments.api.urls")),
    path("api/v1/", include("apps.results.api.urls")),
    path("api/v1/", include("apps.evidence.api.urls")),
    path("api/v1/", include("apps.aggregation.api.urls")),
    path("api/v1/", include("apps.notifications.api.urls")),
    path("api/v1/", include("apps.anomalies.api.urls")),
    path("api/v1/", include("apps.reports.api.urls")),
    path("api/v1/", include("apps.audit.api.urls")),
    path("api/v1/", include("apps.operations.api.urls")),
    path("api/v1/", include("apps.platform_admin.api.urls")),
    path("api/v1/geography/", include("apps.geography.api.urls")),
]

if settings.VTRS_EXPOSE_SCHEMA:
    from apps.core.api.views import SchemaView

    urlpatterns.append(path("api/v1/schema", SchemaView.as_view(), name="schema"))
