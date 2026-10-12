import os
import sys
from pathlib import Path

from celery import Celery, signals

# The Django fixup used to put the project root on the import path; do it here, and again when
# Django is loaded (some launchers replace sys.path between import and worker start).
_ROOT = str(Path(__file__).resolve().parent.parent)


def _ensure_root_on_path() -> None:
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)


_ensure_root_on_path()

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

# Celery's built-in Django fixup is switched off: with it on, every worker throttled to a few
# tasks per second (measured: 200 no-op tasks took 40 s, against 0.3 s without it). What the
# fixup did that matters here is closing database connections around tasks, done below, and
# telling Celery where the Django apps are, done by passing INSTALLED_APPS to autodiscovery.
app = Celery("vtrs", fixups=[])
app.config_from_object("django.conf:settings", namespace="CELERY")


def _installed_apps() -> list[str]:
    """Load Django (the fixup used to), then name the apps whose `tasks` modules to import."""
    import django
    from django.conf import settings

    _ensure_root_on_path()
    django.setup()
    return list(settings.INSTALLED_APPS)


app.autodiscover_tasks(_installed_apps)


def _close_database_connections() -> None:
    from django.db import connections

    connections.close_all()


@signals.worker_process_init.connect
def _forked_worker_starts_clean(**kwargs: object) -> None:
    """A forked worker must not reuse the parent's sockets."""
    _close_database_connections()


@signals.task_postrun.connect
def _task_leaves_no_connection_behind(task: object = None, **kwargs: object) -> None:
    """Connections last one task (CONN_MAX_AGE is 0, for transaction-pooling friendliness).

    Eager tasks (tests, local scripts) run inside the caller's transaction and connection, which
    are not theirs to close."""
    request = getattr(task, "request", None)
    if request is not None and getattr(request, "is_eager", False):
        return
    _close_database_connections()
