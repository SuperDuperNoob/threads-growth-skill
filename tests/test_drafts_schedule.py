"""orbit drafts schedule <id> — headless scheduling for the Hermes agent.

Hermes, after reading `orbit draft --json` and deciding, schedules a chosen
draft to Threads + Facebook. The command sets publish_at + status, then hands
off to Postiz via the existing do_handoff. JSON out, exit 0/non-zero.

We unit-test the pure slot resolver and the result-shaping; the Postiz handoff
itself is covered by existing drafts tests and is mocked here.
"""
from __future__ import annotations
from datetime import datetime, timezone
from unittest.mock import patch

from orbit.commands.drafts import resolve_schedule_slot, do_schedule, HandoffResult


def test_resolve_explicit_slot_passthrough():
    # An explicit ISO slot is used verbatim (Hermes may pin a time).
    slot = resolve_schedule_slot(explicit="2026-06-18T01:00:00Z", taken=set(),
                                 now=datetime(2026, 6, 17, tzinfo=timezone.utc))
    assert slot == "2026-06-18T01:00:00Z"


def test_resolve_picks_next_free_slot_when_none_given():
    now = datetime(2026, 6, 18, 0, 0, tzinfo=timezone.utc)  # 08:00 HKT
    slot = resolve_schedule_slot(explicit=None, taken=set(), now=now)
    # Should be a future UTC ISO string, not None.
    assert slot is not None
    assert datetime.fromisoformat(slot) > now


def test_resolve_skips_taken_slots():
    now = datetime(2026, 6, 18, 0, 0, tzinfo=timezone.utc)
    first = resolve_schedule_slot(explicit=None, taken=set(), now=now)
    # If the first free slot is marked taken, the resolver must return a later one.
    second = resolve_schedule_slot(explicit=None, taken={first}, now=now)
    assert second != first
    assert datetime.fromisoformat(second) > datetime.fromisoformat(first)


def test_do_schedule_success_shape():
    with patch("orbit.commands.drafts.do_handoff",
               return_value=HandoffResult(True, "Handed off draft 5", postiz_id="abc")), \
         patch("orbit.commands.drafts._set_publish_slot"):
        result = do_schedule(5, slot="2026-06-18T01:00:00Z")
    assert result["ok"] is True
    assert result["draft_id"] == 5
    assert result["slot"] == "2026-06-18T01:00:00Z"


def test_do_schedule_failure_shape():
    with patch("orbit.commands.drafts.do_handoff",
               return_value=HandoffResult(False, "Postiz auth expired")), \
         patch("orbit.commands.drafts._set_publish_slot"):
        result = do_schedule(5, slot="2026-06-18T01:00:00Z")
    assert result["ok"] is False
    assert "Postiz" in result["error"]
