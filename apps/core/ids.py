"""UUIDv7 identifiers (RFC 9562).

Time-ordered, so primary keys stay index-friendly and sort by creation time. Within one process
ids are strictly increasing: the 12-bit rand_a field is used as a counter inside a millisecond.
"""

import os
import threading
import time
import uuid
from datetime import UTC, datetime

_lock = threading.Lock()
_last_ms = 0
_counter = 0


def uuid7() -> uuid.UUID:
    global _last_ms, _counter
    with _lock:
        ms = time.time_ns() // 1_000_000
        if ms > _last_ms:
            _last_ms = ms
            # Start low in the 12-bit space so the counter has room before it overflows.
            _counter = int.from_bytes(os.urandom(2), "big") & 0x7FF
        else:
            _counter += 1
            if _counter > 0xFFF:
                _last_ms += 1
                _counter = 0
        ms, counter = _last_ms, _counter
    rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    value = (ms & ((1 << 48) - 1)) << 80 | 0x7 << 76 | counter << 64 | 0b10 << 62 | rand_b
    return uuid.UUID(int=value)


def uuid7_datetime(value: uuid.UUID) -> datetime:
    """Creation time embedded in a UUIDv7 (millisecond precision)."""
    return datetime.fromtimestamp((value.int >> 80) / 1000, tz=UTC)
