import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

django_asgi_app = get_asgi_application()

# Imported after Django is set up: consumers touch models and settings.
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import (  # noqa: E402
    AllowedHostsOriginValidator,
    OriginValidator,
)
from django.conf import settings  # noqa: E402

from apps.aggregation.api.routing import websocket_urlpatterns  # noqa: E402

# The portal lives on its own origin, so sockets accept exactly the configured origins;
# with none configured they fall back to this API's own hosts.
_router = URLRouter(websocket_urlpatterns)
_origin_guard = (
    OriginValidator(_router, settings.VTRS_CORS_ALLOWED_ORIGINS)
    if settings.VTRS_CORS_ALLOWED_ORIGINS
    else AllowedHostsOriginValidator(_router)
)

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": _origin_guard,
    }
)
