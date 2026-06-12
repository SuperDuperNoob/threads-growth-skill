from datetime import datetime, timedelta, timezone

from orbit.scheduling import HKT, format_slot, next_slots


def _hkt(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=HKT)


def test_next_slots_returns_today_remaining_then_tomorrow():
    # 10am HKT Mon — should skip 9am, return 4pm, 9pm, then tomorrow's 9am, 4pm, 9pm
    now = _hkt(2026, 5, 25, 10).astimezone(timezone.utc)
    slots = next_slots(now, taken=set(), count=5)
    hours_hkt = [s.astimezone(HKT).hour for s in slots]
    assert hours_hkt == [16, 21, 9, 16, 21]


def test_next_slots_skips_taken_slots():
    now = _hkt(2026, 5, 25, 8).astimezone(timezone.utc)  # 8am HKT — 9am is next
    # Mark the 9am HKT slot as taken (in UTC ISO form, matching DB convention)
    taken_slot = _hkt(2026, 5, 25, 9).astimezone(timezone.utc).isoformat()
    slots = next_slots(now, taken={taken_slot}, count=3)
    hours_hkt = [s.astimezone(HKT).hour for s in slots]
    assert hours_hkt == [16, 21, 9]  # 9am today is skipped


def test_next_slots_strictly_after_now():
    # 9am HKT on the dot — that slot should NOT be returned (strictly after)
    now = _hkt(2026, 5, 25, 9).astimezone(timezone.utc)
    slots = next_slots(now, taken=set(), count=1)
    assert slots[0].astimezone(HKT).hour == 16


def test_next_slots_end_of_day_rolls_over():
    # 10pm HKT — past all of today's slots, should give tomorrow 9am next
    now = _hkt(2026, 5, 25, 22).astimezone(timezone.utc)
    slots = next_slots(now, taken=set(), count=1)
    assert slots[0].astimezone(HKT).hour == 9
    assert slots[0].astimezone(HKT).day == 26


def test_format_slot_today_tomorrow_later():
    now = _hkt(2026, 5, 25, 10).astimezone(timezone.utc)
    today_4pm = _hkt(2026, 5, 25, 16)
    tomorrow_9am = _hkt(2026, 5, 26, 9)
    later = _hkt(2026, 5, 29, 21)

    assert format_slot(today_4pm, now) == "Today 4pm HKT"
    assert format_slot(tomorrow_9am, now) == "Tomorrow 9am HKT"
    assert "29 May" in format_slot(later, now)
    assert format_slot(later, now).endswith("9pm HKT")
