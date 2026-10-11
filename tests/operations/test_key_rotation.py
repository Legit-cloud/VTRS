"""Rotating the field-encryption key and re-sealing existing rows."""

import base64
from io import StringIO

import pytest
from django.core.management import call_command
from django.db import connection

from apps.accounts.models import User
from apps.core.rls import system_context

pytestmark = pytest.mark.django_db


def _raw(user_id) -> str:
    with connection.cursor() as cursor:
        cursor.execute("SELECT email FROM account_user WHERE id = %s", [user_id])
        return cursor.fetchone()[0]


def test_rotation_reseals_old_rows_and_keeps_them_readable(make_member, settings):
    old = base64.b64encode(b"A" * 32).decode()
    new = base64.b64encode(b"B" * 32).decode()
    settings.VTRS_FIELD_ENCRYPTION_KEYS = {"k1": old}
    settings.VTRS_FIELD_ENCRYPTION_ACTIVE_KEY = "k1"
    member = make_member()
    with system_context():
        User.objects.filter(id=member.user.id).update(email="officer@example.org")
    assert _raw(member.user.id).startswith("v1:k1:")

    # Rotate: a new key becomes active, the old one stays readable.
    settings.VTRS_FIELD_ENCRYPTION_KEYS = {"k1": old, "k2": new}
    settings.VTRS_FIELD_ENCRYPTION_ACTIVE_KEY = "k2"
    with system_context():
        assert User.objects.get(id=member.user.id).email == "officer@example.org"

    dry = StringIO()
    call_command("reencrypt_fields", "--dry-run", stdout=dry)
    assert "would re-encrypt" in dry.getvalue()
    assert _raw(member.user.id).startswith("v1:k1:")  # a dry run changes nothing

    call_command("reencrypt_fields", stdout=StringIO())
    assert _raw(member.user.id).startswith("v1:k2:")
    with system_context():
        assert User.objects.get(id=member.user.id).email == "officer@example.org"

    # The old key can now be retired.
    settings.VTRS_FIELD_ENCRYPTION_KEYS = {"k2": new}
    with system_context():
        assert User.objects.get(id=member.user.id).email == "officer@example.org"

    again = StringIO()
    call_command("reencrypt_fields", stdout=again)
    assert "re-encrypted 0 value(s)" in again.getvalue()
