"""Key material for development and tests only. Production reads real keys from the vault.

The field-encryption and blind-index keys are fixed (so data stays readable across restarts)
and deliberately obvious. The JWT signing key is generated per process.
"""

import base64
import json
import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

DEV_FIELD_KEY = base64.b64encode(b"dev-only-field-key-not-secret-32").decode()
DEV_BLIND_INDEX_KEY = base64.b64encode(b"dev-only-blind-index-key-not-secret").decode()
DEV_OTP_PEPPER = "dev-only-otp-pepper-not-secret"


def _ephemeral_jwt_key() -> str:
    return (
        Ed25519PrivateKey.generate()
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode()
    )


def apply_defaults() -> None:
    os.environ.setdefault("VTRS_JWT_PRIVATE_KEY", _ephemeral_jwt_key())
    os.environ.setdefault("VTRS_FIELD_ENCRYPTION_KEYS", json.dumps({"k1": DEV_FIELD_KEY}))
    os.environ.setdefault("VTRS_BLIND_INDEX_KEY", DEV_BLIND_INDEX_KEY)
    os.environ.setdefault("VTRS_OTP_PEPPER", DEV_OTP_PEPPER)
    os.environ.setdefault("VTRS_SMS_PROVIDER", "apps.notifications.providers.FakeSmsProvider")
