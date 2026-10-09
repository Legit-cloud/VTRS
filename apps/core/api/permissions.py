from typing import TYPE_CHECKING

from django.conf import settings
from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import BasePermission

from apps.core import rls
from apps.core.authz import authorize
from apps.core.errors import MfaRequired

from .actors import resolve_actor

if TYPE_CHECKING:  # DRF imports this module while rest_framework.views is initialising
    from rest_framework.request import Request
    from rest_framework.views import APIView


def required_permission_for(view: object, method: str) -> str | None:
    per_method = getattr(view, "required_permissions", None) or {}
    if method == "HEAD":
        method = "GET"
    return per_method.get(method) or getattr(view, "required_permission", None)


def declared_permissions(view: object) -> set[str]:
    """Every permission a view can require, for policy and matrix tests."""
    perms = set((getattr(view, "required_permissions", None) or {}).values())
    if single := getattr(view, "required_permission", None):
        perms.add(single)
    return perms


class PolicyPermission(BasePermission):
    """Default permission for every view.

    A view must declare `public = True`, a `required_permission`, or `required_permissions`
    (a per-HTTP-method mapping); anything else is denied.
    For protected views this also pins the database session to the actor's organization (RLS),
    enforces mandatory MFA, and attaches the actor to the request.
    """

    def has_permission(self, request: "Request", view: "APIView") -> bool:
        if getattr(view, "public", False) is True:
            return True
        perm = required_permission_for(view, request.method or "")
        if not perm:
            return False
        rls.reset_context()
        actor = resolve_actor(request)
        if actor is None:
            raise NotAuthenticated()
        rls.set_tenant(actor.organization_id)
        request.actor = actor  # type: ignore[attr-defined]
        if (
            settings.VTRS_ENFORCE_MFA
            and actor.requires_mfa
            and actor.mfa_at is None
            and not getattr(view, "allow_without_mfa", False)
        ):
            raise MfaRequired()
        authorize(actor, perm)
        return True
