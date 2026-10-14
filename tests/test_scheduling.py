from datetime import datetime, timedelta, timezone

from orbit.scheduling import MYT, format_slot, next_slots


def _myt(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=MYT)


def test_next_slots_returns_today_remaining_then_tomorrow():
    # 10am MYT Mon — should skip 9am, return 4pm, 9pm, then tomorrow's 9am, 4pm, 9pm
    now = _myt(2026, 5, 25, 10).astimezone(timezone.utc)
    slots = next_slots(now, taken=set(), count=5)
    hours_myt = [s.astimezone(MYT).hour for s in slots]
    assert hours_myt == [16, 21, 9, 16, 21]


def test_next_slots_skips_taken_slots():
    now = _myt(2026, 5, 25, 8).astimezone(timezone.utc)  # 8am MYT — 9am is next
    # Mark the 9am MYT slot as taken (in UTC ISO form, matching DB convention)
    taken_slot = _myt(2026, 5, 25, 9).astimezone(timezone.utc).isoformat()
    slots = next_slots(now, taken={taken_slot}, count=3)
    hours_myt = [s.astimezone(MYT).hour for s in slots]
    assert hours_myt == [16, 21, 9]  # 9am today is skipped


def test_next_slots_strictly_after_now():
    # 9am MYT on the dot — that slot should NOT be returned (strictly after)
    now = _myt(2026, 5, 25, 9).astimezone(timezone.utc)
    slots = next_slots(now, taken=set(), count=1)
    assert slots[0].astimezone(MYT).hour == 16


def test_next_slots_end_of_day_rolls_over():
    # 10pm MYT — past all of today's slots, should give tomorrow 9am next
    now = _myt(2026, 5, 25, 22).astimezone(timezone.utc)
    slots = next_slots(now, taken=set(), count=1)
    assert slots[0].astimezone(MYT).hour == 9
    assert slots[0].astimezone(MYT).day == 26


def test_format_slot_today_tomorrow_later():
    now = _myt(2026, 5, 25, 10).astimezone(timezone.utc)
    today_4pm = _myt(2026, 5, 25, 16)
    tomorrow_9am = _myt(2026, 5, 26, 9)
    later = _myt(2026, 5, 29, 21)

    assert format_slot(today_4pm, now) == "Today 4pm MYT"
    assert format_slot(tomorrow_9am, now) == "Tomorrow 9am MYT"
    assert "29 May" in format_slot(later, now)
    assert format_slot(later, now).endswith("9pm MYT")
