from celery import shared_task

from . import services


@shared_task
def seal_audit_events(max_batches: int = 20) -> int:
    sealed = 0
    while sealed < max_batches and services.seal_pending() is not None:
        sealed += 1
    return sealed


@shared_task
def ensure_audit_partitions() -> None:
    services.ensure_partitions()
