"""The committed OpenAPI file is the contract web and mobile build against (spec section 9).

If this fails after an intended API change, regenerate it:
    python manage.py spectacular --file docs/openapi.yaml --validate
and review the diff: changes within v1 must be additive.
"""

from pathlib import Path

import pytest
from django.core.management import call_command

CONTRACT = Path(__file__).resolve().parents[1] / "docs" / "openapi.yaml"


@pytest.mark.django_db
def test_schema_matches_the_committed_contract(tmp_path):
    generated = tmp_path / "openapi.yaml"
    call_command("spectacular", "--file", str(generated), "--validate")
    assert CONTRACT.exists(), "docs/openapi.yaml is missing; generate it (see module docstring)"
    assert generated.read_text(encoding="utf-8") == CONTRACT.read_text(encoding="utf-8")


@pytest.mark.django_db
def test_schema_endpoint(api_client):
    response = api_client.get("/api/v1/schema")
    assert response.status_code == 200
    assert b"/api/v1/auth/login" in response.content
