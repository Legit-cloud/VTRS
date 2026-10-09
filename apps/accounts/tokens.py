"""Access tokens: short-lived JWTs signed with Ed25519, `kid` in the header for rotation.

Claims identify the session only. Role and scope are always re-read from the database on each
request (spec section 8), so a token never carries authority on its own.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any
from uuid import UUID

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from django.conf import settings
from django.utils import timezone

from apps.core.ids import uuid7

ALGORITHM = "EdDSA"


class TokenError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class AccessClaims:
    user_id: UUID
    organization_id: UUID
    session_id: UUID
    session_version: int
    mfa_at: datetime | None
    expires_at: datetime


@lru_cache(maxsize=8)
def _private_key(pem: str) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise TokenError("The JWT signing key must be Ed25519")
    return key


@lru_cache(maxsize=16)
def _public_key(pem: str) -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(pem.encode())
    if not isinstance(key, Ed25519PublicKey):
        raise TokenError("JWT verification keys must be Ed25519")
    return key


def _verification_keys() -> dict[str, Ed25519PublicKey]:
    keys = {kid: _public_key(pem) for kid, pem in settings.VTRS_JWT_PUBLIC_KEYS.items()}
    keys[settings.VTRS_JWT_KEY_ID] = _private_key(settings.VTRS_JWT_PRIVATE_KEY).public_key()
    return keys


def issue_access_token(
    *,
    user_id: UUID,
    organization_id: UUID,
    session_id: UUID,
    session_version: int,
    mfa_at: datetime | None,
) -> tuple[str, datetime]:
    now = timezone.now()
    expires_at = now + timedelta(seconds=settings.VTRS_ACCESS_TOKEN_SECONDS)
    payload: dict[str, Any] = {
        "iss": settings.VTRS_JWT_ISSUER,
        "aud": settings.VTRS_JWT_AUDIENCE,
        "sub": str(user_id),
        "org": str(organization_id),
        "sid": str(session_id),
        "sv": session_version,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": str(uuid7()),
    }
    if mfa_at is not None:
        payload["mfa_at"] = int(mfa_at.timestamp())
    token = jwt.encode(
        payload,
        _private_key(settings.VTRS_JWT_PRIVATE_KEY),
        algorithm=ALGORITHM,
        headers={"kid": settings.VTRS_JWT_KEY_ID},
    )
    return token, expires_at


def decode_access_token(token: str) -> AccessClaims:
    try:
        kid = str(jwt.get_unverified_header(token).get("kid", ""))
        key = _verification_keys().get(kid)
        if key is None:
            raise TokenError("Unknown signing key")
        payload = jwt.decode(
            token,
            key,
            algorithms=[ALGORITHM],
            audience=settings.VTRS_JWT_AUDIENCE,
            issuer=settings.VTRS_JWT_ISSUER,
            options={"require": ["exp", "iat", "sub", "org", "sid", "sv"]},
        )
        mfa_at = payload.get("mfa_at")
        return AccessClaims(
            user_id=UUID(payload["sub"]),
            organization_id=UUID(payload["org"]),
            session_id=UUID(payload["sid"]),
            session_version=int(payload["sv"]),
            mfa_at=datetime.fromtimestamp(mfa_at, UTC) if mfa_at is not None else None,
            expires_at=datetime.fromtimestamp(payload["exp"], UTC),
        )
    except (jwt.PyJWTError, ValueError, KeyError, TypeError) as exc:
        raise TokenError(str(exc)) from exc
