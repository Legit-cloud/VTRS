import pytest

from apps.notifications.providers import FakeWhatsAppProvider

from ..aggregation.conftest import big_field, field_, reviewed_field  # noqa: F401


@pytest.fixture(autouse=True)
def _clear_provider_outboxes():
    FakeWhatsAppProvider.outbox.clear()
