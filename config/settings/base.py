"""Settings shared by every environment. Everything environment-specific comes from env vars."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

BASE_DIR = Path(__file__).resolve().parents[2]


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable {name}")
    return value


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [part.strip() for part in env(name, default).split(",") if part.strip()]


def database_from_url(url: str) -> dict[str, Any]:
    parts = urlsplit(url)
    if parts.scheme not in {"postgres", "postgresql"}:
        raise RuntimeError("Only PostgreSQL database URLs are supported")
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parts.path.lstrip("/")),
        "USER": unquote(parts.username or ""),
        "PASSWORD": unquote(parts.password or ""),
        "HOST": parts.hostname or "",
        "PORT": str(parts.port or 5432),
        # PgBouncer transaction pooling: no persistent connections, no server-side cursors.
        "CONN_MAX_AGE": 0,
        "DISABLE_SERVER_SIDE_CURSORS": True,
        "OPTIONS": {"options": "-c statement_timeout=5000 -c lock_timeout=2000"},
    }


SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "rest_framework",
    "apps.core",
    "apps.audit",
    "apps.accounts",
    "apps.geography",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.core.middleware.RequestContextMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    }
]

DATABASES = {"default": database_from_url(env("DATABASE_URL"))}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "en"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

# Images never travel through the API (spec section 9), so JSON bodies stay small.
DATA_UPLOAD_MAX_MEMORY_SIZE = 64 * 1024

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.core.api.authentication.BearerChallengeAuthentication"
    ],
    "DEFAULT_PERMISSION_CLASSES": ["apps.core.api.permissions.PolicyPermission"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.KeysetPagination",
    "PAGE_SIZE": 50,
    "EXCEPTION_HANDLER": "apps.core.errors.problem_exception_handler",
    "UNAUTHENTICATED_USER": None,
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_CACHE_URL"),
    }
}

# Celery (spec section 15). Redis is the broker only; PostgreSQL holds the truth via the outbox.
CELERY_BROKER_URL = env("CELERY_BROKER_URL")
CELERY_BROKER_TRANSPORT_OPTIONS = {"visibility_timeout": 3600}
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_SOFT_TIME_LIMIT = 60
CELERY_TASK_TIME_LIMIT = 90
CELERY_BEAT_SCHEDULE = {
    "core.relay_outbox": {"task": "apps.core.tasks.relay_outbox", "schedule": 1.0},
    "core.purge_expired": {"task": "apps.core.tasks.purge_expired", "schedule": 3600.0},
    "audit.seal": {"task": "apps.audit.tasks.seal_audit_events", "schedule": 5.0},
    "audit.partitions": {"task": "apps.audit.tasks.ensure_audit_partitions", "schedule": 86400.0},
}
VTRS_CELERY_QUEUES = (
    "ingest",
    "aggregation",
    "evidence",
    "anomaly",
    "notifications",
    "reports",
    "default",
)

LOGGING: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"request_context": {"()": "apps.core.logging.RequestContextFilter"}},
    "formatters": {"json": {"()": "apps.core.logging.JsonFormatter"}},
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "filters": ["request_context"],
        }
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}

# --- VTRS ---------------------------------------------------------------------------------
# Resolves the acting user (role, organization, scope) for a request. Accounts replaces the
# default once memberships exist (M1).
VTRS_ACTOR_RESOLVER = "apps.core.api.actors.actor_from_user"

# Outbox topic -> (celery task name, queue). Topics without a route are marked published.
VTRS_OUTBOX_ROUTES: dict[str, tuple[str, str]] = {}
VTRS_OUTBOX_RELAY_MIN_AGE_SECONDS = 5
VTRS_OUTBOX_RETENTION_DAYS = 7
VTRS_IDEMPOTENCY_TTL_HOURS = 48

VTRS_AUDIT_SEAL_LAG_SECONDS = 2
VTRS_AUDIT_SEAL_BATCH_SIZE = 5000
VTRS_AUDIT_PARTITION_MONTHS_AHEAD = 3

# FR-6.4.1 expected Oyo master-data shape. The PU count is approximate in the PRD.
VTRS_GEOGRAPHY_EXPECTED = {
    "lgas": 33,
    "wards": 351,
    "polling_units": 6390,
    "polling_unit_tolerance": 0.02,
}
