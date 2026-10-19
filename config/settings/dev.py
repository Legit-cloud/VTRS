import os

from .local_keys import apply_defaults

os.environ.setdefault("DJANGO_SECRET_KEY", "dev-only-not-a-secret")
os.environ.setdefault("DATABASE_URL", "postgres://vtrs_app:vtrs_app_dev@localhost:5432/vtrs")
os.environ.setdefault("REDIS_CACHE_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6380/0")
os.environ.setdefault("REDIS_CHANNELS_URL", "redis://localhost:6381/0")
os.environ.setdefault("VTRS_EXPOSE_SCHEMA", "true")
os.environ.setdefault("VTRS_S3_ENDPOINT_URL", "http://localhost:9000")
os.environ.setdefault("VTRS_S3_ACCESS_KEY", "vtrs-dev")
os.environ.setdefault("VTRS_S3_SECRET_KEY", "vtrs-dev-password")
# The web app on the developer's machine; browsers upload result sheets straight to storage.
os.environ.setdefault("VTRS_CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
apply_defaults()

from .base import *

DEBUG = True
VTRS_ENFORCE_MFA = False
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [
    "rest_framework.renderers.JSONRenderer",
    "rest_framework.renderers.BrowsableAPIRenderer",
]
