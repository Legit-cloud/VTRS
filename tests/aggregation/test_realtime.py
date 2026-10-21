"""Live dashboard feed (FR-6.8.5): who is told about a change, and who is refused."""

import asyncio

import pytest
from asgiref.sync import async_to_sync, sync_to_async
from channels.layers import channel_layers
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.utils import timezone

from apps.accounts.services.sessions import start_session
from apps.aggregation.api import consumers
from apps.aggregation.api.routing import websocket_urlpatterns
from apps.core.domain.permissions import Role

pytestmark = pytest.mark.django_db

APP = URLRouter(websocket_urlpatterns)


@pytest.fixture(autouse=True)
def _fresh_channel_layer():
    channel_layers.backends.clear()
    yield
    channel_layers.backends.clear()


@pytest.fixture(autouse=True)
def _keep_the_test_connection(monkeypatch):
    """`database_sync_to_async` closes "old" connections around each call, which is right in
    production (connections last one request) but would close the test transaction's own."""
    monkeypatch.setattr("channels.db.close_old_connections", lambda: None)


async def _open(token: str | None, election_id, *, raw=None):
    comm = WebsocketCommunicator(APP, "/ws/v1/dashboard")
    connected, _ = await comm.connect()
    assert connected
    await comm.send_json_to(
        raw
        if raw is not None
        else {"type": "auth", "token": token, "election_id": str(election_id)}
    )
    return comm


async def _closed_with(comm) -> int:
    output = await comm.receive_output(timeout=2)
    assert output["type"] == "websocket.close", output
    return output["code"]


def _token(field, member):
    pair = start_session(
        user=member.user,
        membership=member.membership,
        client="WEB",
        mfa_at=timezone.now(),
        ip=None,
    )
    return pair.access_token


def test_an_admin_is_told_when_results_change(field_):
    admin_token = _token(field_, field_.admin)
    pu = field_.pus[0]

    async def scenario():
        comm = await _open(admin_token, field_.election.id)
        ready = await comm.receive_json_from(timeout=2)
        assert ready["type"] == "ready"
        assert ready["scope"] == "ORG"
        assert "not the official inec count" in ready["notice"].lower()

        await sync_to_async(field_.submit)(pu, (50, 25))
        update = await comm.receive_json_from(timeout=3)
        assert update["type"] == "rollup.updated"
        assert update["contest_id"] == str(field_.contest.id)
        assert update["ward_id"] == str(pu.ward_id)
        assert update["revision"] >= 1
        # Ids and a revision only: figures are fetched over REST, where scope is enforced.
        assert set(update) == {"type", "contest_id", "lga_id", "ward_id", "revision", "at"}

        await comm.send_json_to({"type": "ping"})
        assert (await comm.receive_json_from(timeout=2)) == {"type": "pong"}
        await comm.disconnect()

    async_to_sync(scenario)()


def test_a_ward_officer_only_hears_about_their_ward(field_):
    officer = field_.officer(Role.WARD_OFFICER, field_.wards[0])
    token = _token(field_, officer)
    mine, elsewhere = field_.pus_of(field_.wards[0])[0], field_.pus_of(field_.wards[2])[0]

    async def scenario():
        comm = await _open(token, field_.election.id)
        assert (await comm.receive_json_from(timeout=2))["type"] == "ready"

        await sync_to_async(field_.submit)(elsewhere, (1, 1))
        assert await comm.receive_nothing(timeout=0.5)

        await sync_to_async(field_.submit)(mine, (2, 2))
        update = await comm.receive_json_from(timeout=3)
        assert update["ward_id"] == str(field_.wards[0].id)
        await comm.disconnect()

    async_to_sync(scenario)()


def test_an_lga_officer_hears_about_the_whole_lga(field_):
    officer = field_.officer(Role.LGA_OFFICER, field_.lgas[0])
    token = _token(field_, officer)
    sibling_ward_pu = field_.pus_of(field_.wards[1])[0]

    async def scenario():
        comm = await _open(token, field_.election.id)
        assert (await comm.receive_json_from(timeout=2))["type"] == "ready"
        await sync_to_async(field_.submit)(sibling_ward_pu, (3, 3))
        assert (await comm.receive_json_from(timeout=3))["type"] == "rollup.updated"
        await comm.disconnect()

    async_to_sync(scenario)()


def test_refusals(field_, make_org, make_member):
    admin_token = _token(field_, field_.admin)
    agent_token = _token(field_, field_.agents[field_.pus[0].id].member)
    stranger = make_member(Role.PARTY_ADMIN, organization=make_org("Elsewhere"))
    stranger_token = _token(field_, stranger)

    async def scenario():
        cases = [
            (await _open("not-a-token", field_.election.id), consumers.CLOSE_UNAUTHENTICATED),
            (await _open(agent_token, field_.election.id), consumers.CLOSE_FORBIDDEN),
            (await _open(stranger_token, field_.election.id), consumers.CLOSE_NOT_FOUND),
            (await _open(None, None, raw={"type": "hello"}), consumers.CLOSE_MALFORMED),
            (
                await _open(None, None, raw={"type": "auth", "token": admin_token}),
                consumers.CLOSE_MALFORMED,
            ),
        ]
        for comm, expected in cases:
            assert await _closed_with(comm) == expected

    async_to_sync(scenario)()


def test_the_socket_closes_if_nobody_authenticates(field_, monkeypatch):
    monkeypatch.setattr(consumers, "AUTH_SECONDS", 0.2)

    async def scenario():
        comm = WebsocketCommunicator(APP, "/ws/v1/dashboard")
        assert (await comm.connect())[0]
        assert await _closed_with(comm) == consumers.CLOSE_UNAUTHENTICATED

    async_to_sync(scenario)()


def test_a_publisher_failure_never_fails_the_recompute(field_, monkeypatch):
    from apps.aggregation import realtime

    class Broken:
        async def group_send(self, *args, **kwargs):
            raise ConnectionError("redis is down")

    monkeypatch.setattr(realtime, "get_channel_layer", lambda: Broken())
    outcome = field_.submit(field_.pus[0], (5, 5))
    assert outcome["status"] == "ACCEPTED"
    assert asyncio.iscoroutinefunction(Broken.group_send)
