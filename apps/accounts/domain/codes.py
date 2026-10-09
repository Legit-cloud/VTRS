"""One-time codes and bearer tokens. Only hashes are ever stored (spec section 7)."""

import hashlib
import hmac
import secrets

OTP_DIGITS = 6
OTP_MAX_ATTEMPTS = 5


def generate_otp() -> str:
    return f"{secrets.randbelow(10**OTP_DIGITS):0{OTP_DIGITS}d}"


def hash_otp(pepper: bytes, challenge_id: str, code: str) -> str:
    """HMAC-SHA256 with a server pepper, bound to the challenge so codes can't be transplanted."""
    return hmac.new(pepper, f"{challenge_id}:{code}".encode(), hashlib.sha256).hexdigest()


def otp_matches(expected_hash: str, pepper: bytes, challenge_id: str, code: str) -> bool:
    return hmac.compare_digest(expected_hash, hash_otp(pepper, challenge_id, code))


def generate_token() -> str:
    """256 bits of randomness, URL-safe."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    # A plain hash suffices: tokens carry 256 bits of entropy, so there is nothing to brute-force.
    return hashlib.sha256(token.encode()).hexdigest()


def generate_recovery_code() -> str:
    raw = secrets.token_hex(5).upper()
    return f"{raw[:5]}-{raw[5:]}"


def normalize_recovery_code(code: str) -> str:
    return code.strip().upper().replace(" ", "")
