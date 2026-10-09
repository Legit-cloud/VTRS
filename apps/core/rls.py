"""Row Level Security context (spec section 6.2).

Tenant tables only show rows whose organization matches `app.current_org`, set with SET LOCAL
semantics per transaction (safe under PgBouncer transaction pooling). Code that legitimately
works across organizations before an actor is known (sign-in, registration, invitation
acceptance, operator commands) opens an explicit `system_context()`. With neither set,
tenant tables return nothing.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from django.db import DatabaseError, connection, transaction

CURRENT_ORG = "app.current_org"
SYSTEM = "app.rls_system"


def _require_transaction() -> None:
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("RLS context can only be set inside a transaction")


def _set(name: str, value: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config(%s, %s, true)", [name, value])


def _get(name: str) -> str:
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting(%s, true)", [name])
        return cursor.fetchone()[0] or ""


def reset_context() -> None:
    """Start from no tenant and no system access. Called at the start of every API request."""
    _require_transaction()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config(%s, '', true), set_config(%s, 'off', true)", [CURRENT_ORG, SYSTEM]
        )


def set_tenant(organization_id: UUID) -> None:
    _require_transaction()
    _set(CURRENT_ORG, str(organization_id))


@contextmanager
def system_context() -> Iterator[None]:
    """Cross-tenant access for the block. Nests safely: on exit the previous value is restored,
    so an inner block cannot switch off an outer one."""
    _require_transaction()
    previous = _get(SYSTEM) or "off"
    _set(SYSTEM, "on")
    try:
        yield
    finally:
        try:
            _set(SYSTEM, previous)
        except DatabaseError:
            # The transaction is already failing and will roll back, taking the setting with it.
            pass
