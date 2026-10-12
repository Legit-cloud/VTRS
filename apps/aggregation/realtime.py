"""Publishing rollup change notices to connected dashboards (FR-6.8.5)."""

import logging
from typing import Any
from uuid import UUID

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone

from .domain.groups import groups_for_update

logger = logging.getLogger("vtrs.aggregation")

EVENT_TYPE = "rollup.updated"


def announce(
    *,
    election_id: UUID,
    contest_id: UUID,
    lga_id: UUID,
    ward_id: UUID,
    revision: int,
) -> None:
    """Tell every affected dashboard that figures moved. Best effort: a viewer that misses it
    catches up on its next fetch, so a layer outage must never fail the recompute."""
    message: dict[str, Any] = {
        "type": "rollup.notice",  # dispatches to the consumer's rollup_notice handler
        "event": EVENT_TYPE,
        "election_id": str(election_id),
        "contest_id": str(contest_id),
        "lga_id": str(lga_id),
        "ward_id": str(ward_id),
        "revision": revision,
        "at": timezone.now().isoformat(),
    }
    try:
        layer = get_channel_layer()
        if layer is None:
            return
        send = async_to_sync(layer.group_send)
        for group in groups_for_update(election_id, lga_id, ward_id):
            send(group, message)
    except Exception:
        logger.warning("rollup_announce_failed", exc_info=True)
