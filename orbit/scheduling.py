"""Slot generation for Keith's HKT 9am / 4pm / 9pm posting schedule.

Hong Kong has no DST, so a fixed UTC+8 offset is exact year-round.
Slots are stored in the DB as UTC ISO 8601 strings (matches existing convention).
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone

HKT = timezone(timedelta(hours=8))
SLOT_HOURS_HKT = (9, 16, 21)  # 9am, 4pm, 9pm Hong Kong time


def next_slots(
    now: datetime,
    taken: set[str],
    count: int = 6,
) -> list[datetime]:
    """Return the next `count` HKT slots strictly after `now`, skipping any whose
    UTC-ISO representation is already in `taken`. Returned datetimes are in HKT
    so callers can format them for display.
    """
    now_hkt = now.astimezone(HKT)
    out: list[datetime] = []
    day = now_hkt.date()
    # Look up to 14 days ahead — plenty for picking 6 future slots.
    for _ in range(14):
        for hour in SLOT_HOURS_HKT:
            slot = datetime(day.year, day.month, day.day, hour, 0, tzinfo=HKT)
            if slot <= now_hkt:
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
    """Human label like 'Today 4pm HKT' or 'Fri 23 May · 9am HKT'."""
    now_hkt = now.astimezone(HKT)
    today = now_hkt.date()
    tomorrow = today + timedelta(days=1)
    hour12 = slot.strftime("%-I").lower() + slot.strftime("%p").lower()
    if slot.date() == today:
        prefix = "Today"
    elif slot.date() == tomorrow:
        prefix = "Tomorrow"
    else:
        prefix = slot.strftime("%a %-d %b")
    return f"{prefix} {hour12} HKT"
