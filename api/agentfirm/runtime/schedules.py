"""Report schedule cadences: a deliberately small, explicit grammar (no cron).

daily@08:00 · weekly:mon@08:00 · monthly:1@08:00   (local time in the schedule's IANA zone)
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

CADENCE = re.compile(r"^(daily|weekly:(mon|tue|wed|thu|fri|sat|sun)|monthly:([1-9]|1\d|2[0-8]))@([01]\d|2[0-3]):([0-5]\d)$")
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class CadenceError(ValueError):
    pass


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise CadenceError(f"Unknown time zone {name!r}") from exc


def next_run(cadence: str, tz: str, after: datetime | None = None) -> datetime:
    """Next run strictly after `after` (UTC), computed in local time so DST is respected."""
    m = CADENCE.match(cadence)
    if not m:
        raise CadenceError("Cadence must look like daily@08:00, weekly:mon@08:00 or monthly:1@08:00 (days 1-28).")
    z = zone(tz)
    now = (after or datetime.now(UTC)).astimezone(z)
    hh, mm = int(m.group(4)), int(m.group(5))
    cand = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if m.group(1) == "daily":
        while cand <= now:
            cand += timedelta(days=1)
    elif m.group(2):
        target = DAYS.index(m.group(2))
        cand += timedelta(days=(target - cand.weekday()) % 7)
        while cand <= now:
            cand += timedelta(days=7)
    else:
        day = int(m.group(3))
        cand = cand.replace(day=day)
        while cand <= now:
            cand = (cand.replace(day=1) + timedelta(days=32)).replace(day=day)
    return cand.replace(tzinfo=z).astimezone(UTC)
