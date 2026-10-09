"""Bot challenge for public OTP-sending endpoints (anti SMS-pumping, spec section 7).

The provider is an open decision. "disabled" is only acceptable in development and tests;
production settings refuse to start with it.
"""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from rest_framework.exceptions import ValidationError


def verify(token: str | None, ip: str | None) -> None:
    provider = settings.VTRS_BOT_CHALLENGE_PROVIDER
    if provider == "disabled":
        return
    if provider == "always_fail":  # lets tests prove the endpoints honour the check
        raise ValidationError({"bot_token": ["Bot challenge failed."]}, code="bot_challenge_failed")
    raise ImproperlyConfigured(f"Bot challenge provider {provider!r} is not implemented yet")
