from typing import TYPE_CHECKING

from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import BasePermission

from apps.core.authz import authorize

from .actors import resolve_actor

if TYPE_CHECKING:  # DRF imports this module while rest_framework.views is initialising
    from rest_framework.request import Request
    from rest_framework.views import APIView


class PolicyPermission(BasePermission):
    """Default permission for every view.

    A view must declare `public = True` or a `required_permission`; anything else is denied.
    The resolved actor is attached to the request for selectors and services.
    """

    def has_permission(self, request: "Request", view: "APIView") -> bool:
        if getattr(view, "public", False) is True:
            return True
        perm = getattr(view, "required_permission", None)
        if not perm:
            return False
        actor = resolve_actor(request)
        if actor is None:
            raise NotAuthenticated()
        request.actor = actor  # type: ignore[attr-defined]
        authorize(actor, perm)
        return True
