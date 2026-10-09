from django.conf import settings
from django.utils.module_loading import import_string
from rest_framework.request import Request

from apps.core.domain.actor import Actor


def actor_from_user(request: Request) -> Actor | None:
    """Default resolver: the authenticated user object supplies its own actor."""
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    get_actor = getattr(user, "get_actor", None)
    return get_actor() if callable(get_actor) else None


def resolve_actor(request: Request) -> Actor | None:
    resolver = import_string(settings.VTRS_ACTOR_RESOLVER)
    return resolver(request)
