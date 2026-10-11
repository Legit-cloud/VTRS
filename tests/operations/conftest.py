import pytest

from apps.evidence.storage import get_storage

from ..aggregation.conftest import big_field, field_, reviewed_field  # noqa: F401


@pytest.fixture
def storage():
    return get_storage()
