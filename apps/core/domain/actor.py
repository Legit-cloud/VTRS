"""Who is acting: role, organization and geographic scope (spec section 8)."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from .permissions import Perm, Role, effective_permissions, requires_mfa


class ScopeKind(StrEnum):
    ORG = "ORG"
    LGA = "LGA"
    WARD = "WARD"
    PU = "PU"


ROLE_SCOPE_KIND: Mapping[Role, ScopeKind] = {
    Role.PARTY_ADMIN: ScopeKind.ORG,
    Role.LGA_OFFICER: ScopeKind.LGA,
    Role.WARD_OFFICER: ScopeKind.WARD,
    Role.PU_AGENT: ScopeKind.PU,
}


@dataclass(frozen=True, slots=True)
class Scope:
    kind: ScopeKind
    ids: frozenset[UUID] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.kind is ScopeKind.ORG and self.ids:
            raise ValueError("An organization-wide scope carries no geography ids")


@dataclass(frozen=True, slots=True)
class Actor:
    user_id: UUID
    organization_id: UUID
    role: Role
    scope: Scope
    granted: frozenset[Perm] = field(default_factory=frozenset)
    session_id: UUID | None = None
    # When this session last passed a second factor; None if it never has.
    mfa_at: datetime | None = None

    def __post_init__(self) -> None:
        # Fail closed on an inconsistent membership rather than guessing a scope.
        if ROLE_SCOPE_KIND[self.role] is not self.scope.kind:
            raise ValueError(f"Role {self.role} requires a {ROLE_SCOPE_KIND[self.role]} scope")

    @property
    def permissions(self) -> frozenset[Perm]:
        return effective_permissions(self.role, self.granted)

    @property
    def requires_mfa(self) -> bool:
        return requires_mfa(self.role, self.permissions)

    def has_perm(self, perm: Perm) -> bool:
        return perm in self.permissions

    def mfa_within(self, max_age: timedelta, now: datetime) -> bool:
        return self.mfa_at is not None and now - self.mfa_at <= max_age
