import base64
from uuid import uuid4

import pytest
from cryptography.exceptions import InvalidTag
from django.db import connection

from apps.accounts.models import Membership, User
from apps.core import rls
from apps.core.crypto import blind_index, decrypt, encrypt
from apps.organizations.models import Organization

KEY_2 = base64.b64encode(b"second-test-key-32-bytes-long!!!").decode()


def test_encryption_round_trip_and_context_binding():
    token = encrypt("+2348031234567", context="account_user.phone")
    assert token.startswith("v1:k1:")
    assert "2348031234567" not in token
    assert decrypt(token, context="account_user.phone") == "+2348031234567"
    with pytest.raises(InvalidTag):
        decrypt(token, context="account_user.email")  # can't be moved to another column


def test_encryption_is_randomized():
    assert encrypt("same", context="c") != encrypt("same", context="c")


def test_key_rotation_keeps_old_ciphertexts_readable(settings):
    old = encrypt("ada@example.org", context="c")
    settings.VTRS_FIELD_ENCRYPTION_KEYS = {
        **settings.VTRS_FIELD_ENCRYPTION_KEYS,
        "k2": KEY_2,
    }
    settings.VTRS_FIELD_ENCRYPTION_ACTIVE_KEY = "k2"
    new = encrypt("ada@example.org", context="c")
    assert new.startswith("v1:k2:")
    assert decrypt(old, context="c") == decrypt(new, context="c") == "ada@example.org"


def test_blind_index_is_deterministic_and_keyed(settings):
    first = blind_index("email", "ada@example.org")
    assert first == blind_index("email", "ada@example.org")
    assert first != blind_index("phone", "ada@example.org")
    settings.VTRS_BLIND_INDEX_KEY = base64.b64encode(b"another-key").decode()
    assert blind_index("email", "ada@example.org") != first


@pytest.mark.django_db
def test_contact_details_are_stored_encrypted(make_member):
    member = make_member()
    with connection.cursor() as cursor:
        cursor.execute("SELECT email, phone FROM account_user WHERE id = %s", [member.user.id])
        email, phone = cursor.fetchone()
    assert member.email not in email and email.startswith("v1:")
    assert member.phone not in phone and phone.startswith("v1:")
    assert User.objects.get(id=member.user.id).email == member.email


# --- Row Level Security -------------------------------------------------------------------


@pytest.mark.django_db
def test_tests_run_as_the_application_role():
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_user")
        assert cursor.fetchone()[0] == "vtrs_app"


@pytest.mark.django_db
def test_tenant_tables_are_empty_without_context(make_member):
    make_member()
    rls.reset_context()
    assert Organization.objects.count() == 0
    assert Membership.objects.count() == 0


@pytest.mark.django_db
def test_tenant_context_shows_only_that_organization(make_member):
    ours, theirs = make_member(), make_member()
    rls.reset_context()
    rls.set_tenant(ours.organization.id)
    assert list(Organization.objects.values_list("id", flat=True)) == [ours.organization.id]
    assert list(Membership.objects.values_list("user_id", flat=True)) == [ours.user.id]
    assert not Membership.objects.filter(user_id=theirs.user.id).exists()


@pytest.mark.django_db
def test_rls_blocks_writes_into_another_organization(make_member):
    ours, theirs = make_member(), make_member()
    rls.reset_context()
    rls.set_tenant(ours.organization.id)
    # Even an unscoped UPDATE cannot reach the other tenant's rows.
    updated = Membership.objects.all().update(granted_permissions=["evidence.view"])
    assert updated == 1
    with rls.system_context():
        assert Membership.objects.get(user=theirs.user).granted_permissions == []


@pytest.mark.django_db
def test_system_context_sees_everything_and_closes(make_member):
    make_member(), make_member()
    rls.reset_context()
    with rls.system_context():
        assert Organization.objects.count() == 2
    assert Organization.objects.count() == 0


@pytest.mark.django_db
def test_nested_system_context_does_not_switch_off_the_outer_one(make_member):
    """Regression: an inner block used to reset the flag to 'off' on exit, so the rest of the
    outer block (e.g. creating a membership while accepting an invitation) was refused."""
    member = make_member()
    rls.reset_context()
    with rls.system_context():
        with rls.system_context():
            pass
        assert Membership.objects.filter(user=member.user).exists()
    assert not Membership.objects.filter(user=member.user).exists()


@pytest.mark.django_db
def test_each_request_starts_without_tenant_context(make_member, client_as):
    """Regression: a tenant set by one request must not leak into the next in the same
    transaction (it hid the nesting bug from the API tests)."""
    client = client_as(make_member())
    assert client.get("/api/v1/me").status_code == 200  # sets app.current_org
    client.credentials()
    client.get("/api/v1/health/live")  # a public request resets it
    assert Organization.objects.count() == 0


def test_rls_context_requires_a_transaction():
    with pytest.raises(RuntimeError):
        rls.set_tenant(uuid4())
