from django.core.exceptions import ImproperlyConfigured

from .base import *

DEBUG = False

if VTRS_BOT_CHALLENGE_PROVIDER == "disabled":
    raise ImproperlyConfigured("Production needs a bot challenge provider (anti SMS-pumping)")
if VTRS_SMS_PROVIDER.endswith("FakeSmsProvider"):
    raise ImproperlyConfigured("Production cannot use the fake SMS provider")
if VTRS_MALWARE_SCANNER.endswith("EicarOnlyScanner"):
    raise ImproperlyConfigured("Production needs a real malware scanner for evidence")
if not REDIS_CHANNELS_URL:
    raise ImproperlyConfigured("Production needs REDIS_CHANNELS_URL for live dashboards")
for _origin in VTRS_CORS_ALLOWED_ORIGINS:
    if _origin == "*" or not _origin.startswith("https://"):
        raise ImproperlyConfigured(f"CORS origins must be exact https:// origins, not {_origin!r}")
if VTRS_BOT_CHALLENGE_PROVIDER == "always_fail":
    raise ImproperlyConfigured("The test bot challenge provider cannot run in production")
if VTRS_BOT_CHALLENGE_PROVIDER in {"turnstile", "hcaptcha", "recaptcha"} and not (
    VTRS_BOT_CHALLENGE_SECRET
):
    raise ImproperlyConfigured("VTRS_BOT_CHALLENGE_SECRET is required for the bot challenge")
if any(
    name.endswith("TwilioSmsProvider") or name.endswith("TwilioWhatsAppProvider")
    for name in (VTRS_SMS_PROVIDER, VTRS_WHATSAPP_PROVIDER)
):
    if not (VTRS_TWILIO_ACCOUNT_SID and VTRS_TWILIO_AUTH_TOKEN and VTRS_PUBLIC_BASE_URL):
        raise ImproperlyConfigured(
            "Twilio needs VTRS_TWILIO_ACCOUNT_SID, VTRS_TWILIO_AUTH_TOKEN and "
            "VTRS_PUBLIC_BASE_URL (for delivery receipts)"
        )
if not VTRS_INVITATION_LINK.startswith("https://"):
    raise ImproperlyConfigured("VTRS_INVITATION_LINK must point at the web app over HTTPS")
if VTRS_FEATURE_WHATSAPP_ALERTS and VTRS_WHATSAPP_PROVIDER.endswith("FakeWhatsAppProvider"):
    raise ImproperlyConfigured("WhatsApp alerts are on but the provider is the fake")
if VTRS_EVIDENCE_STORAGE != "s3":
    raise ImproperlyConfigured("Production evidence must live in private object storage")

SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Strict"
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")
