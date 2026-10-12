"""Settings shared by every environment. Everything environment-specific comes from env vars."""

from __future__ import annotations

import json
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
        # Each request is one transaction, so the RLS tenant setting (SET LOCAL) covers it.
        "ATOMIC_REQUESTS": True,
        "OPTIONS": {"options": "-c statement_timeout=5000 -c lock_timeout=2000"},
    }


SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS")
# Exact origins of the web portal (https://portal.example.org), for CORS and WebSockets.
VTRS_CORS_ALLOWED_ORIGINS = env_list("VTRS_CORS_ALLOWED_ORIGINS")

INSTALLED_APPS = [
    "daphne",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.postgres",
    "rest_framework",
    "drf_spectacular",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "apps.core",
    "apps.audit",
    "apps.organizations",
    "apps.accounts",
    "apps.geography",
    "apps.elections",
    "apps.assignments",
    "apps.results",
    "apps.evidence",
    "apps.anomalies",
    "apps.aggregation",
    "apps.notifications",
    "apps.reports",
    "apps.operations",
    "apps.platform_admin",
]


MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.core.middleware.ApiBoundaryMiddleware",
    "apps.core.middleware.RequestContextMiddleware",
    "apps.core.middleware.MinimumAppVersionMiddleware",
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
        "apps.accounts.api.authentication.AccessTokenAuthentication"
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
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

# Live dashboard fan-out (FR-6.8.5). Empty means in-process, which only works when the
# publisher and the sockets share a process (tests, a single dev server); production
# settings require Redis.
REDIS_CHANNELS_URL = env("REDIS_CHANNELS_URL", "")
CHANNEL_LAYERS = {
    "default": (
        {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [REDIS_CHANNELS_URL], "capacity": 1000, "expiry": 10},
        }
        if REDIS_CHANNELS_URL
        else {"BACKEND": "channels.layers.InMemoryChannelLayer"}
    )
}
CELERY_BROKER_TRANSPORT_OPTIONS = {"visibility_timeout": 3600}
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
# Each worker slot reserves four messages. With one, a worker that has handed its slots to
# running tasks stops reading until a polling tick, and short tasks queue up behind that gap
# (measured: 300 tasks took 62 s at 1 and 3.7 s at 4). Give the `reports` queue its own worker
# with `--prefetch-multiplier=1`, so a long export never holds messages other workers could run.
CELERY_WORKER_PREFETCH_MULTIPLIER = 4
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_SOFT_TIME_LIMIT = 60
CELERY_TASK_TIME_LIMIT = 90
CELERY_BEAT_SCHEDULE = {
    "core.relay_outbox": {"task": "apps.core.tasks.relay_outbox", "schedule": 1.0},
    "core.purge_expired": {"task": "apps.core.tasks.purge_expired", "schedule": 3600.0},
    "audit.seal": {"task": "apps.audit.tasks.seal_audit_events", "schedule": 5.0},
    "audit.partitions": {"task": "apps.audit.tasks.ensure_audit_partitions", "schedule": 86400.0},
    "evidence.reconcile_uploads": {
        "task": "apps.evidence.tasks.reconcile_pending_uploads",
        "schedule": 300.0,
    },
    "evidence.partitions": {
        "task": "apps.evidence.tasks.ensure_custody_partitions",
        "schedule": 86400.0,
    },
    "anomalies.escalate": {
        "task": "apps.anomalies.tasks.escalate_overdue",
        "schedule": 60.0,
    },
    "anomalies.missing_evidence": {
        "task": "apps.anomalies.tasks.check_missing_evidence",
        "schedule": 300.0,
    },
    "aggregation.drain": {
        "task": "apps.aggregation.tasks.drain_stale_marks",
        "schedule": 10.0,
    },
    "aggregation.self_heal": {
        "task": "apps.aggregation.tasks.self_heal_rollups",
        "schedule": 300.0,
    },
    "reports.purge": {
        "task": "apps.reports.tasks.purge_expired_exports",
        "schedule": 3600.0,
    },
    "notifications.retry": {
        "task": "apps.notifications.tasks.retry_failed_deliveries",
        "schedule": 60.0,
    },
}
CELERY_TASK_ROUTES = {
    "apps.evidence.tasks.verify_evidence": {"queue": "evidence"},
    "apps.anomalies.tasks.analyze_version": {"queue": "anomaly"},
    "apps.anomalies.tasks.analyze_evidence": {"queue": "anomaly"},
    "apps.anomalies.tasks.flag_quarantined": {"queue": "anomaly"},
    "apps.anomalies.tasks.route_flags": {"queue": "anomaly"},
    "apps.notifications.tasks.deliver_notifications": {"queue": "notifications"},
    "apps.reports.tasks.build_export": {"queue": "reports"},
    "apps.results.tasks.notify_review_decision": {"queue": "notifications"},
    "apps.aggregation.tasks.update_rollups": {"queue": "aggregation"},
    "apps.aggregation.tasks.build_election_rollups": {"queue": "aggregation"},
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

SPECTACULAR_SETTINGS = {
    "TITLE": "VTRS API",
    "DESCRIPTION": (
        "Vote Tracking & Recording Solution. Results shown are provisional party data, "
        "never an official declaration."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": "/api/v1",
    # Several models have a `status`; give each enum a stable name for generated clients.
    "ENUM_NAME_OVERRIDES": {
        "ElectionStatusEnum": "apps.elections.domain.rules.ElectionStatus",
        "UserStatusEnum": "apps.accounts.models.UserStatus",
        # Devices and assignments share the ACTIVE/REVOKED choice set.
        "ActiveRevokedStatusEnum": "apps.assignments.models.AssignmentStatus",
    },
}
# The schema endpoint is off unless enabled (never on the public production hostname).
VTRS_EXPOSE_SCHEMA = env_bool("VTRS_EXPOSE_SCHEMA", False)

EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "localhost")
EMAIL_PORT = int(env("EMAIL_PORT", "1025"))
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "VTRS <no-reply@vtrs.invalid>")

OTP_TOTP_ISSUER = "VTRS"

# --- VTRS ---------------------------------------------------------------------------------
# Resolves the acting user (role, organization, scope) for a request.
VTRS_ACTOR_RESOLVER = "apps.core.api.actors.actor_from_auth"

# Identity (spec section 7). Keys and peppers come from the secrets vault in production.
VTRS_JWT_PRIVATE_KEY = env("VTRS_JWT_PRIVATE_KEY")
VTRS_JWT_KEY_ID = env("VTRS_JWT_KEY_ID", "k1")
# Retired keys still accepted for verification during rotation: {"kid": "<public PEM>"}.
VTRS_JWT_PUBLIC_KEYS: dict[str, str] = json.loads(env("VTRS_JWT_PUBLIC_KEYS", "{}"))
VTRS_JWT_ISSUER = "vtrs"
VTRS_JWT_AUDIENCE = "vtrs-api"
VTRS_ACCESS_TOKEN_SECONDS = 600
VTRS_MOBILE_SESSION_DAYS = 7
VTRS_WEB_SESSION_HOURS = 12
VTRS_ENFORCE_MFA = True
VTRS_MFA_STEP_UP_SECONDS = 600

VTRS_OTP_PEPPER = env("VTRS_OTP_PEPPER")
VTRS_OTP_HOURLY_PER_DESTINATION = 5
VTRS_OTP_HOURLY_PER_IP = 20
VTRS_SMS_ALLOWED_PREFIXES = env_list("VTRS_SMS_ALLOWED_PREFIXES", "+234")
VTRS_SMS_PROVIDER = env("VTRS_SMS_PROVIDER")
# Open decision: bot challenge provider. "disabled" is refused by production settings.
VTRS_BOT_CHALLENGE_PROVIDER = env("VTRS_BOT_CHALLENGE_PROVIDER", "disabled")
# turnstile, hcaptcha or recaptcha: the secret key from the provider's console.
VTRS_BOT_CHALLENGE_SECRET = env("VTRS_BOT_CHALLENGE_SECRET", "")

# Public base URL of this API (used to tell providers where to send delivery receipts).
VTRS_PUBLIC_BASE_URL = env("VTRS_PUBLIC_BASE_URL", "")

# Twilio (SMS and WhatsApp). Used when the provider settings name the Twilio adapters.
VTRS_TWILIO_ACCOUNT_SID = env("VTRS_TWILIO_ACCOUNT_SID", "")
VTRS_TWILIO_AUTH_TOKEN = env("VTRS_TWILIO_AUTH_TOKEN", "")
VTRS_TWILIO_SMS_FROM = env("VTRS_TWILIO_SMS_FROM", "")
VTRS_TWILIO_MESSAGING_SERVICE_SID = env("VTRS_TWILIO_MESSAGING_SERVICE_SID", "")
VTRS_TWILIO_WHATSAPP_FROM = env("VTRS_TWILIO_WHATSAPP_FROM", "")

# Firebase Cloud Messaging: the service account JSON, as the secrets vault holds it.
VTRS_FCM_SERVICE_ACCOUNT_JSON = env("VTRS_FCM_SERVICE_ACCOUNT_JSON", "")

# {"kid": "<base64 32-byte key>"}; the active key encrypts, all keys decrypt.
VTRS_FIELD_ENCRYPTION_KEYS: dict[str, str] = json.loads(env("VTRS_FIELD_ENCRYPTION_KEYS"))
VTRS_FIELD_ENCRYPTION_ACTIVE_KEY = env("VTRS_FIELD_ENCRYPTION_ACTIVE_KEY", "k1")
VTRS_BLIND_INDEX_KEY = env("VTRS_BLIND_INDEX_KEY")

VTRS_INVITATION_TTL_HOURS = 72
# PB-06 (decided): up to three agents may cover one polling unit per election. A second
# agent's submission for the same unit is flagged DUPLICATE_SOURCE for review (M3/M5).
VTRS_MAX_AGENTS_PER_POLLING_UNIT = int(env("VTRS_MAX_AGENTS_PER_POLLING_UNIT", "3"))
VTRS_INVITATION_LINK = env("VTRS_INVITATION_LINK", "vtrs://invite?token={token}")
VTRS_MIN_APP_VERSION = env("VTRS_MIN_APP_VERSION", "1.0.0")

# Evidence storage (spec section 12): "s3" (RustFS locally, any S3-compatible store) or "local".
VTRS_EVIDENCE_STORAGE = env("VTRS_EVIDENCE_STORAGE", "s3")
VTRS_EVIDENCE_LOCAL_ROOT = env("VTRS_EVIDENCE_LOCAL_ROOT", str(BASE_DIR / "var" / "evidence"))
VTRS_S3_ENDPOINT_URL = env("VTRS_S3_ENDPOINT_URL", "")
VTRS_S3_BUCKET = env("VTRS_S3_BUCKET", "vtrs-evidence")
VTRS_S3_REGION = env("VTRS_S3_REGION", "us-east-1")
VTRS_S3_ACCESS_KEY = env("VTRS_S3_ACCESS_KEY", "")
VTRS_S3_SECRET_KEY = env("VTRS_S3_SECRET_KEY", "")
VTRS_EVIDENCE_UPLOAD_URL_SECONDS = 900
VTRS_EVIDENCE_DOWNLOAD_URL_SECONDS = 60

# Exports and evidence packs (FR-6.10.5, PB-09). Conservative defaults pending the
# approved policy: files live 72 hours, three jobs per person at a time, and a pack
# must be narrowed past 2,000 photos or 1 GiB.
VTRS_EXPORT_RETENTION_HOURS = 72
VTRS_EXPORT_MAX_ACTIVE = 3
VTRS_EVIDENCE_PACK_MAX_FILES = 2000
VTRS_EVIDENCE_PACK_MAX_BYTES = 1024**3

# Retention of election records, in years after RECONCILED (PB-09, DG-04). Nothing is
# deleted automatically: `retention_report` lists what has passed its period so a
# person with legal sign-off can act on it.
VTRS_RETENTION_YEARS = {"evidence": 7, "results": 10, "audit": 10, "notifications": 1}
VTRS_EVIDENCE_MAX_PIXELS = 40_000_000
# Open decision: production malware scanner (ClamAV or managed). Prod refuses this stand-in.
VTRS_MALWARE_SCANNER = env("VTRS_MALWARE_SCANNER", "apps.evidence.scanning.EicarOnlyScanner")
VTRS_CLAMD_HOST = env("VTRS_CLAMD_HOST", "localhost")
VTRS_CLAMD_PORT = int(env("VTRS_CLAMD_PORT", "3310"))
VTRS_CLAMD_TIMEOUT_SECONDS = float(env("VTRS_CLAMD_TIMEOUT_SECONDS", "20"))

VTRS_THROTTLE_RATES = {
    "submit_device": "60/min",
    "login_ip": "5/min",
    "login_account": "5/min",
    "otp_ip": "10/min",
    "registration_ip": "5/hour",
    "password_ip": "5/min",
    "invitation_ip": "10/min",
    "refresh_ip": "60/min",
}

# Feature flags for open decisions (section 22). All off by default.
VTRS_FEATURE_FACE_VERIFICATION = False  # FR-6.1.3, PB-08, SEC-09
VTRS_FEATURE_WHATSAPP_ALERTS = False  # FR-6.12.3

VTRS_PUSH_PROVIDER = env("VTRS_PUSH_PROVIDER", "apps.notifications.providers.FakePushProvider")
VTRS_WHATSAPP_PROVIDER = env(
    "VTRS_WHATSAPP_PROVIDER", "apps.notifications.providers.FakeWhatsAppProvider"
)

# Anomaly rule thresholds (spec section 13, PB-10). Defaults follow common election-
# monitoring practice and are documented in apps/anomalies/domain/contextual.py.
# Override any field of `Thresholds` here, e.g. {"geofence_m": 500.0}.
VTRS_ANOMALY_THRESHOLDS: dict[str, float | int] = {}

# Alert routing and escalation. Empty keeps the built-in matrix (domain/escalation.py).
# Per severity: notify (WARD/LGA/ADMIN), channels, ack_minutes, escalation_channels.
VTRS_ESCALATION_MATRIX: dict[str, dict[str, object]] = {}

# Outbox topic -> (celery task name, queue). Topics without a route are marked published.
# result.version_accepted also gains the anomaly rules in M5.
# A topic maps to one (task, queue) or to a list of them: independent consumers.
_UPDATE_ROLLUPS = ("apps.aggregation.tasks.update_rollups", "aggregation")
VTRS_OUTBOX_ROUTES: dict[str, tuple[str, str] | list[tuple[str, str]]] = {
    "evidence.uploaded": ("apps.evidence.tasks.verify_evidence", "evidence"),
    "evidence.verified": ("apps.anomalies.tasks.analyze_evidence", "anomaly"),
    "evidence.quarantined": ("apps.anomalies.tasks.flag_quarantined", "anomaly"),
    "result.version_accepted": [
        _UPDATE_ROLLUPS,
        ("apps.anomalies.tasks.analyze_version", "anomaly"),
    ],
    "result.review_decided": [
        _UPDATE_ROLLUPS,
        ("apps.results.tasks.notify_review_decision", "notifications"),
    ],
    "anomaly.flags_raised": [
        _UPDATE_ROLLUPS,
        ("apps.anomalies.tasks.route_flags", "anomaly"),
    ],
    "anomaly.flag_changed": _UPDATE_ROLLUPS,
    "notification.created": (
        "apps.notifications.tasks.deliver_notifications",
        "notifications",
    ),
    "election.opened": ("apps.aggregation.tasks.build_election_rollups", "aggregation"),
    "export.requested": ("apps.reports.tasks.build_export", "reports"),
}
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
