"""Progressive lockout after repeated failed sign-ins: 1, 5, then 30 minutes (spec section 7)."""

from datetime import timedelta

THRESHOLD = 5


def lockout_for(consecutive_failures: int) -> timedelta | None:
    if consecutive_failures < THRESHOLD:
        return None
    if consecutive_failures < THRESHOLD * 2:
        return timedelta(minutes=1)
    if consecutive_failures < THRESHOLD * 3:
        return timedelta(minutes=5)
    return timedelta(minutes=30)
