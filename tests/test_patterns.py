import pytest
import json
from orbit.patterns import PatternStore

def test_pattern_store_creates_dir(orbit_home):
    ps = PatternStore(orbit_home)
    assert (orbit_home / "patterns").exists()

def test_load_missing_platform_returns_defaults(orbit_home):
    ps = PatternStore(orbit_home)
    p = ps.load("linkedin")
    assert p["platform"] == "linkedin"
    assert p["sample_size"] == 0
    assert p["top_hooks"] == []

def test_save_and_load_pattern(orbit_home):
    ps = PatternStore(orbit_home)
    data = {
        "platform": "threads",
        "sample_size": 10,
        "top_hooks": [{"type": "anti_demo", "avg_multiplier": 2.1, "sample": 4}],
        "optimal_length": {"min": 80, "max": 150, "unit": "words"},
        "best_posting_times": [],
        "top_topics": ["ai_agents"],
        "weak_topics": [],
        "ai_tone_flags": [],
        "engagement_benchmarks": {"views_median": 0, "likes_median": 0, "comments_median": 0},
    }
    ps.save("threads", data)
    loaded = ps.load("threads")
    assert loaded["sample_size"] == 10
    assert loaded["top_hooks"][0]["type"] == "anti_demo"
