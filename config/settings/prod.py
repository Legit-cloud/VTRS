from django.core.exceptions import ImproperlyConfigured

from .base import *

DEBUG = False

if VTRS_BOT_CHALLENGE_PROVIDER == "disabled":
    raise ImproperlyConfigured("Production needs a bot challenge provider (anti SMS-pumping)")
if VTRS_SMS_PROVIDER.endswith("FakeSmsProvider"):
    raise ImproperlyConfigured("Production cannot use the fake SMS provider")
if VTRS_MALWARE_SCANNER.endswith("EicarOnlyScanner"):
    raise ImproperlyConfigured("Production needs a real malware scanner for evidence")
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
