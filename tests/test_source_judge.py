from orbit.source_judge import build_source_judge_prompt


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
