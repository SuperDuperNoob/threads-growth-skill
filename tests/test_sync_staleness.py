from datetime import datetime, timezone

from orbit.db import DB, evaluate_staleness, last_metric_pull_per_platform


NOW = datetime(2026, 6, 14, 12, 0, 0, tzinfo=timezone.utc)


def test_fresh_platform_not_stale():
    last = {"threads": "2026-06-14T06:00:00+00:00"}  # 6 hours ago
    out = evaluate_staleness(last, now=NOW, platforms=["threads"], stale_after_days=3)
    assert out["threads"]["stale"] is False
    assert out["threads"]["never"] is False
    assert out["threads"]["days"] < 1


def test_old_platform_is_stale():
    last = {"linkedin": "2026-05-26T05:48:04+00:00"}  # ~19 days ago
    out = evaluate_staleness(last, now=NOW, platforms=["linkedin"], stale_after_days=3)
    assert out["linkedin"]["stale"] is True
    assert out["linkedin"]["never"] is False
    assert round(out["linkedin"]["days"]) == 19


def test_never_pulled_is_stale_and_never():
    out = evaluate_staleness({}, now=NOW, platforms=["youtube"], stale_after_days=3)
    assert out["youtube"]["stale"] is True
    assert out["youtube"]["never"] is True
    assert out["youtube"]["days"] is None


def test_exactly_at_threshold_is_not_stale():
    # 3 days ago exactly — strictly-greater-than means not yet stale.
    last = {"threads": "2026-06-11T12:00:00+00:00"}
    out = evaluate_staleness(last, now=NOW, platforms=["threads"], stale_after_days=3)
    assert out["threads"]["stale"] is False


def test_naive_timestamp_treated_as_utc():
    # Some legacy rows may lack tzinfo; must not raise on subtraction.
    last = {"threads": "2026-06-14T06:00:00"}
    out = evaluate_staleness(last, now=NOW, platforms=["threads"], stale_after_days=3)
    assert out["threads"]["stale"] is False


def test_last_metric_pull_reads_max_per_platform(tmp_path):
    db = DB(home=tmp_path)
    db.conn["metrics"].insert_all([
        {"platform": "threads", "views": 1, "pulled_at": "2026-06-10T00:00:00+00:00"},
        {"platform": "threads", "views": 1, "pulled_at": "2026-06-13T00:00:00+00:00"},
        {"platform": "linkedin", "views": 1, "pulled_at": "2026-05-26T00:00:00+00:00"},
    ])
    out = last_metric_pull_per_platform(db.conn)
    assert out["threads"] == "2026-06-13T00:00:00+00:00"
    assert out["linkedin"] == "2026-05-26T00:00:00+00:00"
    assert "youtube" not in out
