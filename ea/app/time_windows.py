from __future__ import annotations

from datetime import datetime, time as dtime, timedelta, timezone


def local_next_day_window_utc(now_local: datetime, *, days_ahead: int = 1) -> tuple[str, datetime, datetime]:
    """
    Return `(target_day_key, utc_start, utc_end)` for a local-day window.

    `now_local` must be timezone-aware. The returned UTC boundaries are derived
    from local midnight boundaries, so DST transitions are handled correctly.
    """
    if now_local.tzinfo is None:
        raise ValueError("now_local must be timezone-aware")
    ahead = max(0, int(days_ahead))
    target_day_local = (now_local + timedelta(days=ahead)).date()
    next_day_local = target_day_local + timedelta(days=1)
    start_local = datetime.combine(target_day_local, dtime.min, tzinfo=now_local.tzinfo)
    end_local = datetime.combine(next_day_local, dtime.min, tzinfo=now_local.tzinfo)
    return (
        target_day_local.isoformat(),
        start_local.astimezone(timezone.utc),
        end_local.astimezone(timezone.utc),
    )

