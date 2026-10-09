from dataclasses import dataclass
from uuid import UUID

from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.request import Request

from apps.accounts import tokens
from apps.accounts.errors import InvalidToken
from apps.accounts.services import sessions
from apps.core.domain.actor import Actor


@dataclass(frozen=True)
class AuthenticatedUser:
    """What DRF sees as `request.user`. Authority lives in the actor (`request.auth`)."""

    id: UUID
    is_authenticated: bool = True


class AccessTokenAuthentication(BaseAuthentication):
    def authenticate(self, request: Request) -> tuple[AuthenticatedUser, Actor] | None:
        parts = get_authorization_header(request).split()
        if not parts or parts[0].lower() != b"bearer":
            return None
        if len(parts) != 2:
            raise InvalidToken()
        try:
            claims = tokens.decode_access_token(parts[1].decode())
        except (tokens.TokenError, UnicodeDecodeError):
            raise InvalidToken() from None
        actor = sessions.resolve_actor(claims)
        return AuthenticatedUser(actor.user_id), actor

    def authenticate_header(self, request: Request) -> str:
        return 'Bearer realm="vtrs"'
