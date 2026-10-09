"""Geographic scoping in the query layer (spec section 8).

Tenant models declare SCOPE_LOOKUPS mapping "org", "lga", "ward" and "pu" to their (usually
denormalized) columns. Reads go through `for_actor`, so scope is one indexed predicate.
"""

from collections.abc import Mapping
from uuid import UUID

from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.db.models import Q

from .domain.actor import Actor, Scope, ScopeKind

_KIND_KEYS = {ScopeKind.LGA: "lga", ScopeKind.WARD: "ward", ScopeKind.PU: "pu"}


def scope_q(scope: Scope, organization_id: UUID | None, lookups: Mapping[str, str]) -> Q:
    q = Q()
    if org_field := lookups.get("org"):
        q &= Q(**{org_field: organization_id})
    if scope.kind is ScopeKind.ORG:
        return q
    field = lookups.get(_KIND_KEYS[scope.kind])
    if field is None:
        # Fail closed: a model that can't be narrowed to this scope must not be readable by it.
        raise ImproperlyConfigured(f"No {scope.kind} scope lookup configured")
    return q & Q(**{f"{field}__in": sorted(scope.ids)})


class ScopedQuerySet(models.QuerySet):
    def for_actor(self, actor: Actor) -> "ScopedQuerySet":
        lookups: Mapping[str, str] | None = getattr(self.model, "SCOPE_LOOKUPS", None)
        if not lookups or "org" not in lookups:
            raise ImproperlyConfigured(
                f"{self.model.__name__} must declare SCOPE_LOOKUPS with an 'org' entry"
            )
        return self.filter(scope_q(actor.scope, actor.organization_id, lookups))

    def in_organization(self, actor: Actor) -> "ScopedQuerySet":
        """Organization-wide reference data (elections, contests, candidates): every member of
        the organization may read it, whatever their geographic scope."""
        lookups: Mapping[str, str] | None = getattr(self.model, "SCOPE_LOOKUPS", None)
        if not lookups or "org" not in lookups:
            raise ImproperlyConfigured(
                f"{self.model.__name__} must declare SCOPE_LOOKUPS with an 'org' entry"
            )
        return self.filter(**{lookups["org"]: actor.organization_id})
