import time
from datetime import UTC, datetime, timedelta

from apps.core.ids import uuid7, uuid7_datetime


def test_uuid7_version_and_variant():
    value = uuid7()
    assert value.version == 7
    assert value.variant == "specified in RFC 4122"


def test_uuid7_is_strictly_increasing_within_a_process():
    ids = [uuid7() for _ in range(10_000)]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)


def test_uuid7_embeds_creation_time():
    before = datetime.now(UTC) - timedelta(milliseconds=5)
    value = uuid7()
    time.sleep(0.001)
    assert before <= uuid7_datetime(value) <= datetime.now(UTC) + timedelta(milliseconds=5)
