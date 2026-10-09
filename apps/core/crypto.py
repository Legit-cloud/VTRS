"""Application-level encryption for contact details, with HMAC blind indexes for lookups.

Spec section 16: email and phone are encrypted per field (AES-256-GCM, the column name bound in
as associated data so ciphertexts cannot be swapped between columns). Lookups use a keyed HMAC
of the normalized value, never the plaintext. Keys come from settings for now; a key-service
data key replaces the local keyring in production (open decision: hosting, PB-12).
"""

import base64
import hashlib
import hmac
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

_VERSION = "v1"


def _keyring() -> tuple[str, dict[str, bytes]]:
    keys = {
        kid: base64.b64decode(value) for kid, value in settings.VTRS_FIELD_ENCRYPTION_KEYS.items()
    }
    active = settings.VTRS_FIELD_ENCRYPTION_ACTIVE_KEY
    if active not in keys or any(len(key) != 32 for key in keys.values()):
        raise ImproperlyConfigured("Field encryption needs 32-byte keys and a valid active key id")
    return active, keys


def encrypt(plaintext: str, *, context: str) -> str:
    active, keys = _keyring()
    nonce = os.urandom(12)
    sealed = AESGCM(keys[active]).encrypt(nonce, plaintext.encode(), context.encode())
    return f"{_VERSION}:{active}:{base64.urlsafe_b64encode(nonce + sealed).decode()}"


def decrypt(token: str, *, context: str) -> str:
    version, kid, payload = token.split(":", 2)
    if version != _VERSION:
        raise ValueError(f"Unknown ciphertext version {version}")
    _, keys = _keyring()
    raw = base64.urlsafe_b64decode(payload)
    return AESGCM(keys[kid]).decrypt(raw[:12], raw[12:], context.encode()).decode()


def blind_index(kind: str, normalized_value: str) -> str:
    key = base64.b64decode(settings.VTRS_BLIND_INDEX_KEY)
    return hmac.new(key, f"{kind}:{normalized_value}".encode(), hashlib.sha256).hexdigest()
