from collections.abc import Callable, Iterable
from dataclasses import dataclass
from uuid import UUID

import pytest
from rest_framework.test import APIClient

from apps.core.domain.actor import ROLE_SCOPE_KIND, Actor, Scope, ScopeKind
from apps.core.domain.permissions import Perm, Role
from apps.core.ids import uuid7


@dataclass
class ActorUser:
    """Stands in for an authenticated user until accounts and tokens exist (M1)."""

    actor: Actor
    is_authenticated: bool = True

    def get_actor(self) -> Actor:
        return self.actor


@pytest.fixture
def make_actor() -> Callable[..., Actor]:
    def _make(
        role: Role = Role.PARTY_ADMIN,
        scope_ids: Iterable[UUID] = (),
        organization_id: UUID | None = None,
        granted: Iterable[Perm] = (),
    ) -> Actor:
        kind = ROLE_SCOPE_KIND[role]
        ids = frozenset() if kind is ScopeKind.ORG else frozenset(scope_ids) or frozenset({uuid7()})
        return Actor(
            user_id=uuid7(),
            organization_id=organization_id or uuid7(),
            role=role,
            scope=Scope(kind, ids),
            granted=frozenset(granted),
        )

    return _make


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def client_as(api_client: APIClient) -> Callable[[Actor], APIClient]:
    def _as(actor: Actor) -> APIClient:
        api_client.force_authenticate(user=ActorUser(actor))
        return api_client

    return _as
