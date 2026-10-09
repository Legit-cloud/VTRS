from django.conf import settings
from django.utils.module_loading import import_string
from rest_framework.request import Request

from apps.core.domain.actor import Actor


def actor_from_auth(request: Request) -> Actor | None:
    """Default resolver: the authentication class leaves the resolved actor in `request.auth`."""
    auth = request.auth
    return auth if isinstance(auth, Actor) else None


def resolve_actor(request: Request) -> Actor | None:
    resolver = import_string(settings.VTRS_ACTOR_RESOLVER)
    return resolver(request)
