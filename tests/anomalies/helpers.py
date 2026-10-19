"""Shared helpers for the anomaly, escalation and notification tests."""

import io
import random
from typing import Any

from PIL import Image

from apps.anomalies.models import AnomalyFlag
from apps.core.rls import system_context
from apps.evidence.models import EvidenceFile
from apps.evidence.storage import get_storage
from apps.notifications.models import Delivery, Notification
from apps.results.models import ResultVersion

from ..results.conftest import manifest_entry


def flags_of(version_id: Any = None, **filters: Any) -> list[AnomalyFlag]:
    with system_context():
        qs = AnomalyFlag.objects.all()
        if version_id is not None:
            qs = qs.filter(result_version_id=version_id)
        return list(qs.filter(**filters).order_by("created_at", "rule_code"))


def rules_of(version_id: Any) -> set[str]:
    return {f.rule_code for f in flags_of(version_id)}


def version_state(version_id: Any) -> str:
    with system_context():
        return ResultVersion.objects.get(id=version_id).state


def notifications_for(user_id: Any, **filters: Any) -> list[Notification]:
    with system_context():
        return list(
            Notification.objects.filter(user_id=user_id, **filters)
            .prefetch_related("deliveries")
            .order_by("created_at")
        )


def deliveries(notification: Notification) -> dict[str, str]:
    with system_context():
        return dict(
            Delivery.objects.filter(notification_id=notification.id).values_list(
                "channel", "status"
            )
        )


def unit_with_coordinates(field: Any, ward_index: int = 0) -> Any:
    for pu in field.pus_of(field.wards[ward_index]):
        if pu.latitude is not None:
            return pu
    raise AssertionError("synthetic data should give at least one unit coordinates per ward")


def noise_photo(seed: int, quality: int = 90, size: int = 64) -> bytes:
    """A textured image, so different seeds give clearly different difference hashes."""
    rng = random.Random(seed)  # noqa: S311 - test data
    image = Image.new("RGB", (size, size))
    image.putdata(
        [(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(size * size)]
    )
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


def reencode(data: bytes, quality: int) -> bytes:
    buffer = io.BytesIO()
    Image.open(io.BytesIO(data)).save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


def submit_with_photo(field: Any, pu: Any, photo: bytes, votes=(120, 80), **overrides: Any) -> dict:
    """Submit the numbers, then attach the photo as the browser does: request the upload, put the
    bytes and confirm (the worker verifies)."""
    outcome = field.submit(pu, votes, **overrides)
    entry = manifest_entry(photo)
    client = field.agents[pu.id].client
    upload = {**entry, "version_id": outcome["version_id"]}
    assert client.post("/api/v1/evidence/uploads", upload, format="json").status_code == 200
    with system_context():
        key = EvidenceFile.objects.get(id=entry["evidence_id"]).object_key
    get_storage().write(key, photo, mime="image/jpeg")
    response = client.post(f"/api/v1/evidence/{entry['evidence_id']}/complete")
    assert response.status_code == 200, response.content
    outcome["evidence_id"] = entry["evidence_id"]
    return outcome
