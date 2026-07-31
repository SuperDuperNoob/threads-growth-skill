from orbit.source_judge import build_source_judge_prompt
from orbit.source_judge import parse_source_judgment, rank_judged


def test_prompt_includes_every_source_and_recent_topics():
    sources = [
        {"author": "a", "url": "u1", "text": "Claude Code did X"},
        {"author": "b", "url": "u2", "text": "niche research paper Y"},
    ]
    recent = ["Claude Code migration story"]
    top = [{"content": "有人用 Claude Code...", "views": 190000, "like_rate": 1.1}]
    p = build_source_judge_prompt(sources, recent, top)
    # every source rendered with its index
    assert "[0]" in p and "[1]" in p
    assert "Claude Code did X" in p
    assert "niche research paper Y" in p
    # recent topics surfaced for the novelty axis
    assert "Claude Code migration story" in p
    # the three axes named
    assert "novelty" in p.lower()
    assert "audience" in p.lower() or "width" in p.lower()
    assert "fit" in p.lower()
    # instructs strict JSON array back
    assert "JSON" in p


def test_parse_valid_json():
    raw = '[{"index":0,"novelty":8,"width":7,"fit":9,"reason":"fresh"}]'
    out = parse_source_judgment(raw)
    assert out == [{"index": 0, "novelty": 8, "width": 7, "fit": 9, "reason": "fresh"}]


def test_parse_tolerates_prose_around_json():
    raw = 'Here you go:\n[{"index":0,"novelty":5,"width":5,"fit":5,"reason":"x"}]\nDone'
    assert parse_source_judgment(raw)[0]["index"] == 0


def test_parse_bad_json_returns_none():
    assert parse_source_judgment("not json at all") is None
    assert parse_source_judgment("") is None


def test_parse_drops_out_of_range_or_malformed_entries():
    raw = '[{"index":0,"novelty":8,"width":7,"fit":9,"reason":"ok"},{"nope":1}]'
    out = parse_source_judgment(raw)
    assert len(out) == 1  # malformed entry dropped


def test_rank_weights_novelty_higher():
    judged = [
        {"index": 0, "novelty": 10, "width": 5, "fit": 5, "reason": "a"},
        {"index": 1, "novelty": 2, "width": 10, "fit": 10, "reason": "b"},
    ]
    ranked = rank_judged(judged, novelty_weight=1.5)
    assert ranked[0]["index"] == 0


def test_rank_default_weight_is_one():
    judged = [
        {"index": 0, "novelty": 6, "width": 5, "fit": 5, "reason": "a"},
        {"index": 1, "novelty": 5, "width": 6, "fit": 6, "reason": "b"},
    ]
    ranked = rank_judged(judged, novelty_weight=1.0)
    assert ranked[0]["index"] == 1
