import os

from .local_keys import apply_defaults

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-not-a-secret")
os.environ.setdefault(
    "DATABASE_URL",
    os.environ.get("TEST_DATABASE_URL", "postgres://postgres:postgres@localhost:5432/postgres"),
)
os.environ.setdefault("REDIS_CACHE_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_BROKER_URL", "memory://")
os.environ.setdefault("VTRS_EXPOSE_SCHEMA", "true")
os.environ.setdefault("VTRS_EVIDENCE_STORAGE", "local")
apply_defaults()

from .base import *

ALLOWED_HOSTS = ["testserver"]

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Argon2 is deliberately slow; tests don't need that.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Generous by default; throttle tests lower them explicitly.
VTRS_THROTTLE_RATES = {scope: "1000/min" for scope in VTRS_THROTTLE_RATES}
VTRS_OTP_HOURLY_PER_DESTINATION = 1000
VTRS_OTP_HOURLY_PER_IP = 1000

LOGGING["root"]["level"] = "WARNING"
