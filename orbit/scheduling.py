"""Slot generation for Malaysia (MYT) posting schedule.

Malaysia has no DST, so a fixed UTC+8 offset is exact year-round (same
offset as HKT — but slots are tuned to MY audience: sol posts 5x/day and
this skill's schedule is derived for KL/MYT engagement windows).
Slots are stored in the DB as UTC ISO 8601 strings (matches existing convention).
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone

MYT = timezone(timedelta(hours=8))
SLOT_HOURS_MYT = (9, 16, 21)  # 9am, 4pm, 9pm Malaysia time (KL prime windows)


def next_slots(
    now: datetime,
    taken: set[str],
    count: int = 6,
) -> list[datetime]:
    """Return the next `count` MYT slots strictly after `now`, skipping any whose
    UTC-ISO representation is already in `taken`. Returned datetimes are in MYT
    so callers can format them for display.
    """
    now_myt = now.astimezone(MYT)
    out: list[datetime] = []
    day = now_myt.date()
    # Look up to 14 days ahead — plenty for picking 6 future slots.
    for _ in range(14):
        for hour in SLOT_HOURS_MYT:
            slot = datetime(day.year, day.month, day.day, hour, 0, tzinfo=MYT)
            if slot <= now_myt:
                continue
            slot_iso = slot.astimezone(timezone.utc).isoformat()
            if slot_iso in taken:
                continue
            out.append(slot)
            if len(out) >= count:
                return out
        day += timedelta(days=1)
    return out


def format_slot(slot: datetime, now: datetime) -> str:
    """Human label like 'Today 4pm MYT' or 'Fri 23 May · 9am MYT'."""
    now_myt = now.astimezone(MYT)
    today = now_myt.date()
    tomorrow = today + timedelta(days=1)
    hour12 = slot.strftime("%-I").lower() + slot.strftime("%p").lower()
    if slot.date() == today:
        prefix = "Today"
    elif slot.date() == tomorrow:
        prefix = "Tomorrow"
    else:
        prefix = slot.strftime("%a %-d %b")
    return f"{prefix} {hour12} MYT"
