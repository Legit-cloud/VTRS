from celery import shared_task

from . import services


@shared_task
def relay_outbox() -> int:
    return services.relay_pending()


@shared_task
def purge_expired() -> dict[str, int]:
    return services.purge_expired()
