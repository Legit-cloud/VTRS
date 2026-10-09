"""Service-layer authorization check, run before every state change and every scoped read."""

from rest_framework.exceptions import NotAuthenticated

from .domain.actor import Actor
from .domain.permissions import Perm
from .errors import Forbidden

# Pseudo-permission for endpoints any signed-in, active user may call.
AUTHENTICATED = "authenticated"


def authorize(actor: Actor | None, perm: Perm | str) -> Actor:
    if actor is None:
        raise NotAuthenticated()
    if perm == AUTHENTICATED:
        return actor
    if not actor.has_perm(Perm(perm)):
        raise Forbidden()
    return actor
