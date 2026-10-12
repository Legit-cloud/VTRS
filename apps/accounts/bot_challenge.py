"""Bot challenge for public OTP-sending endpoints (anti SMS-pumping, spec section 7).

Turnstile, hCaptcha and reCAPTCHA share one verification protocol: POST the secret, the client's
token and its address, read `success`. "disabled" is only acceptable in development and tests;
production settings refuse to start with it. If the provider cannot be reached the request is
refused (503) rather than waved through: an open OTP endpoint is the attack this guards against.
"""

import logging

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from rest_framework.exceptions import APIException, ValidationError

from apps.core import http

logger = logging.getLogger("vtrs.accounts")

VERIFY_URLS = {
    "turnstile": "https://challenges.cloudflare.com/turnstile/v0/siteverify",
    "hcaptcha": "https://api.hcaptcha.com/siteverify",
    "recaptcha": "https://www.google.com/recaptcha/api/siteverify",
}


class BotChallengeUnavailable(APIException):
    status_code = 503
    default_detail = "The verification service is unavailable. Try again shortly."
    default_code = "bot_challenge_unavailable"


def _failed() -> ValidationError:
    return ValidationError({"bot_token": ["Bot challenge failed."]}, code="bot_challenge_failed")


def verify(token: str | None, ip: str | None) -> None:
    provider = settings.VTRS_BOT_CHALLENGE_PROVIDER
    if provider == "disabled":
        return
    if provider == "always_fail":  # lets tests prove the endpoints honour the check
        raise _failed()
    url = VERIFY_URLS.get(provider)
    if url is None:
        raise ImproperlyConfigured(f"Unknown bot challenge provider {provider!r}")
    if not settings.VTRS_BOT_CHALLENGE_SECRET:
        raise ImproperlyConfigured("VTRS_BOT_CHALLENGE_SECRET is not set")
    if not token or len(token) > 4096:
        raise _failed()
    form = {"secret": settings.VTRS_BOT_CHALLENGE_SECRET, "response": token}
    if ip:
        form["remoteip"] = ip
    try:
        response = http.post(url, form=form, timeout=5.0)
    except http.HttpError:
        logger.warning("bot_challenge_unreachable", extra={"provider": provider})
        raise BotChallengeUnavailable() from None
    if not response.ok:
        logger.warning("bot_challenge_http_error", extra={"status": response.status})
        raise BotChallengeUnavailable()
    if response.json().get("success") is not True:
        raise _failed()
