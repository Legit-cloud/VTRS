"""Service-layer authorization check, run before every state change and every scoped read."""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import NotAuthenticated

from .domain.actor import Actor
from .domain.permissions import Perm
from .errors import Forbidden, StepUpRequired

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


def require_recent_mfa(actor: Actor, max_age_seconds: int | None = None) -> None:
    """Step-up check for sensitive actions: role/scope changes, exports, evidence packs."""
    if max_age_seconds is None:
        max_age_seconds = settings.VTRS_MFA_STEP_UP_SECONDS
    if not actor.mfa_within(timedelta(seconds=max_age_seconds), timezone.now()):
        raise StepUpRequired()
