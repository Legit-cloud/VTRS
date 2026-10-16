"""Live dashboard feed: WebSocket at /ws/v1/dashboard (FR-6.8.5).

Protocol
  1. Connect, then within AUTH_SECONDS send {"type": "auth", "token": "<access token>",
     "election_id": "<uuid>"}. Tokens are not accepted in the URL (they would be logged).
  2. Reply {"type": "ready", ...} or the socket closes with a code:
       4400 malformed message   4401 bad, expired or revoked token / auth timeout
       4403 not allowed (no dashboard permission, or MFA missing)   4404 unknown election
  3. {"type": "rollup.updated", contest_id, lga_id, ward_id, revision, at} on every change
     in the viewer's scope. It carries ids only: refetch the figures over REST.
  4. The socket closes with 4401 when the access token expires; refresh and reconnect.
  5. {"type": "ping"} is answered with {"type": "pong"}.
"""

import asyncio
import contextlib
from typing import Any
from uuid import UUID

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException

from apps.accounts import tokens
from apps.accounts.services import sessions
from apps.aggregation.domain.groups import groups_for_viewer
from apps.aggregation.domain.tally import PROVISIONAL_NOTICE
from apps.core import rls
from apps.core.authz import authorize, mfa_mandatory
from apps.core.domain.actor import Actor
from apps.core.domain.permissions import Perm
from apps.elections import selectors as elections

AUTH_SECONDS = 10

CLOSE_MALFORMED = 4400
CLOSE_UNAUTHENTICATED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_NOT_FOUND = 4404


class Refused(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


@database_sync_to_async
def _authenticate(token: str, election_id: UUID) -> tuple[Actor, Any]:
    try:
        claims = tokens.decode_access_token(token)
        with transaction.atomic():
            actor = sessions.resolve_actor(claims)
            rls.set_tenant(actor.organization_id)
            try:
                authorize(actor, Perm.DASHBOARD_VIEW)
            except APIException:
                raise Refused(CLOSE_FORBIDDEN) from None
            if mfa_mandatory(actor.role, actor.permissions) and actor.mfa_at is None:
                raise Refused(CLOSE_FORBIDDEN)
            try:
                elections.election_for(actor, election_id)
            except APIException:
                raise Refused(CLOSE_NOT_FOUND) from None
    except (tokens.TokenError, APIException):
        raise Refused(CLOSE_UNAUTHENTICATED) from None
    return actor, claims.expires_at


class DashboardConsumer(AsyncJsonWebsocketConsumer):  # type: ignore[misc]
    groups_joined: list[str]

    async def connect(self) -> None:
        self.groups_joined = []
        self.authenticated = False
        self._deadline: asyncio.Task[None] | None = None
        await self.accept()
        self._deadline = asyncio.create_task(self._close_after(AUTH_SECONDS))

    async def _close_after(self, seconds: float) -> None:
        await asyncio.sleep(max(seconds, 0))
        await self.close(code=CLOSE_UNAUTHENTICATED)

    async def disconnect(self, code: int) -> None:
        if self._deadline is not None:
            self._deadline.cancel()
        for group in self.groups_joined:
            await self.channel_layer.group_discard(group, self.channel_name)

    async def receive_json(self, content: Any, **kwargs: Any) -> None:
        if not isinstance(content, dict):
            await self.close(code=CLOSE_MALFORMED)
            return
        kind = content.get("type")
        if kind == "ping":
            await self.send_json({"type": "pong"})
            return
        if kind != "auth" or self.authenticated:
            await self.close(code=CLOSE_MALFORMED)
            return
        try:
            token = content["token"]
            election_id = UUID(str(content["election_id"]))
            if not isinstance(token, str):
                raise ValueError
        except (KeyError, ValueError):
            await self.close(code=CLOSE_MALFORMED)
            return
        try:
            actor, expires_at = await _authenticate(token, election_id)
        except Refused as refused:
            await self.close(code=refused.code)
            return

        self.authenticated = True
        if self._deadline is not None:
            self._deadline.cancel()
        self.groups_joined = groups_for_viewer(election_id, actor.scope.kind.value, actor.scope.ids)
        for group in self.groups_joined:
            await self.channel_layer.group_add(group, self.channel_name)
        # The socket lives no longer than the access token that opened it.
        remaining = (expires_at - timezone.now()).total_seconds()
        self._deadline = asyncio.create_task(self._close_after(remaining))
        await self.send_json(
            {
                "type": "ready",
                "election_id": str(election_id),
                "scope": actor.scope.kind.value,
                "notice": PROVISIONAL_NOTICE,
            }
        )

    async def rollup_notice(self, message: dict[str, Any]) -> None:
        if not self.authenticated:
            return
        await self.send_json(
            {
                "type": "rollup.updated",
                "contest_id": message["contest_id"],
                "lga_id": message["lga_id"],
                "ward_id": message["ward_id"],
                "revision": message["revision"],
                "at": message["at"],
            }
        )

    async def close(self, code: int | None = None, reason: str | None = None) -> None:
        if self._deadline is not None and not self._deadline.done():
            # Closing from the deadline task itself must not cancel the close in progress.
            current = asyncio.current_task()
            if self._deadline is not current:
                self._deadline.cancel()
        with contextlib.suppress(Exception):
            await super().close(code=code, reason=reason)
