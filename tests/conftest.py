import itertools
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from importlib import import_module
from uuid import UUID

import pytest
from django.core import mail
from django.core.cache import cache
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Membership, User, UserStatus
from apps.accounts.services.sessions import start_session
from apps.core.crypto import blind_index
from apps.core.domain.actor import ROLE_SCOPE_KIND, Actor, Scope, ScopeKind
from apps.core.domain.permissions import Perm, Role
from apps.core.ids import uuid7
from apps.core.rls import system_context
from apps.notifications.providers import FakeSmsProvider
from apps.organizations.models import Organization, OrganizationStatus

PASSWORD = "correct-horse-battery-staple"

# Tests run as the application role, not the superuser that creates the test database, so
# Row Level Security and the restricted grants on immutable tables are exercised for real.
APP_ROLE_SETUP = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vtrs_app') THEN
        CREATE ROLE vtrs_app NOLOGIN;
    END IF;
END;
$$;
GRANT USAGE ON SCHEMA public TO vtrs_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO vtrs_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO vtrs_app;
"""
# Migrations that narrow the app role's grants, re-applied after the blanket grant above.
RESTRICTING_MIGRATIONS = ["apps.audit.migrations.0002_audit_storage"]


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock(), connection.cursor() as cursor:
        cursor.execute(APP_ROLE_SETUP)
        for module in RESTRICTING_MIGRATIONS:
            cursor.execute(import_module(module).GRANTS)


@pytest.fixture(autouse=True)
def _run_as_app_role(request):
    if "db" not in request.fixturenames and not request.node.get_closest_marker("django_db"):
        return
    request.getfixturevalue("db")
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL ROLE vtrs_app")


@pytest.fixture
def as_superuser():
    """For tests that simulate an insider with database superuser rights."""

    def _switch():
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")

    return _switch


@pytest.fixture(autouse=True)
def _clear_outboxes_and_cache():
    FakeSmsProvider.outbox.clear()
    mail.outbox = []
    cache.clear()  # throttle counters, OTP budgets and the session deny-list


# --- Pure actors (no database) ------------------------------------------------------------


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


# --- Real organizations, users and sessions -----------------------------------------------

_counter = itertools.count(1)


@dataclass
class Member:
    user: User
    membership: Membership
    organization: Organization

    @property
    def email(self) -> str:
        return self.user.email

    @property
    def phone(self) -> str:
        return self.user.phone


@pytest.fixture
def make_org(db) -> Callable[..., Organization]:
    def _make(name: str = "Test Party", status: str = OrganizationStatus.ACTIVE) -> Organization:
        with system_context():
            return Organization.objects.create(name=name, status=status)

    return _make


@pytest.fixture
def make_member(db, make_org) -> Callable[..., Member]:
    def _make(
        role: Role = Role.PARTY_ADMIN,
        scope_ids: Iterable[UUID] = (),
        organization: Organization | None = None,
        granted: Iterable[str] = (),
        mfa_enabled: bool = False,
    ) -> Member:
        n = next(_counter)
        org = organization or make_org()
        email, phone = f"user{n}@example.org", f"+234803{n:07d}"
        kind = ROLE_SCOPE_KIND[role]
        ids = [] if kind is ScopeKind.ORG else (list(scope_ids) or [uuid7()])
        with system_context():
            user = User.objects.create_user(
                password=PASSWORD,
                full_name=f"User {n}",
                email=email,
                email_index=blind_index("email", email),
                phone=phone,
                phone_index=blind_index("phone", phone),
                status=UserStatus.ACTIVE,
                mfa_enabled=mfa_enabled,
            )
            membership = Membership.objects.create(
                user=user,
                organization=org,
                role=role,
                scope_type=kind,
                scope_ids=ids,
                granted_permissions=list(granted),
            )
        return Member(user, membership, org)

    return _make


@pytest.fixture
def token_for(db) -> Callable[..., str]:
    def _token(member: Member, *, mfa: bool = True) -> str:
        pair = start_session(
            user=member.user,
            membership=member.membership,
            client="WEB",
            device=None,
            mfa_at=timezone.now() if mfa else None,
            ip=None,
        )
        return pair.access_token

    return _token


class CommitClient(APIClient):
    """Runs on-commit callbacks (notifications, outbox) after each request, as production does."""

    def __init__(self, capture, **kwargs):
        super().__init__(**kwargs)
        self._capture = capture

    def request(self, **kwargs):
        with self._capture(execute=True):
            return super().request(**kwargs)


@pytest.fixture
def api_client(django_capture_on_commit_callbacks) -> APIClient:
    return CommitClient(django_capture_on_commit_callbacks)


@pytest.fixture
def client_as(django_capture_on_commit_callbacks, token_for) -> Callable[..., APIClient]:
    def _as(member: Member, *, mfa: bool = True) -> APIClient:
        client = CommitClient(django_capture_on_commit_callbacks)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(member, mfa=mfa)}")
        return client

    return _as


class Inbox:
    """Messages the fake SMS provider and the test mail backend have 'sent'."""

    def messages(self, to: str | None = None) -> list[str]:
        sms = [(m.to, m.body) for m in FakeSmsProvider.outbox]
        email = [(e.to[0], e.body) for e in mail.outbox]
        return [body for dest, body in sms + email if to is None or dest == to]

    def last_code(self, to: str | None = None) -> str:
        for body in reversed(self.messages(to)):
            if match := re.search(r"\b(\d{6})\b", body):
                return match.group(1)
        raise AssertionError(f"No code sent to {to}")

    def last_invitation_token(self, to: str | None = None) -> str:
        for body in reversed(self.messages(to)):
            if match := re.search(r"token=([A-Za-z0-9_-]+)", body):
                return match.group(1)
        raise AssertionError(f"No invitation sent to {to}")


@pytest.fixture
def inbox() -> Inbox:
    return Inbox()
