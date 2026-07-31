from orbit.critic import build_critic_prompt, parse_critique


def test_critic_prompt_names_four_axes_and_the_draft():
    p = build_critic_prompt("有人開源了一個工具。\n免費。", top_posts=[])
    assert "有人開源了一個工具" in p
    for axis in ("hook", "payoff", "slop", "chinese"):
        assert axis in p.lower()
    assert "JSON" in p


def test_parse_valid_critique():
    raw = '{"hook":8,"payoff":6,"anti_slop":7,"zh_naturalness":9,"total":30,"fixes":["tighten last line"]}'
    c = parse_critique(raw)
    assert c["total"] == 30
    assert c["fixes"] == ["tighten last line"]


def test_parse_computes_total_when_missing():
    raw = '{"hook":8,"payoff":6,"anti_slop":7,"zh_naturalness":9,"fixes":[]}'
    c = parse_critique(raw)
    assert c["total"] == 30


def test_parse_bad_json_returns_none():
    assert parse_critique("garbage") is None
    assert parse_critique("") is None


def test_parse_missing_axis_returns_none():
    assert parse_critique('{"hook":8,"payoff":6}') is None


from orbit.critic import build_refine_prompt, pick_better


def test_refine_prompt_includes_draft_and_fixes():
    crit = {"hook": 4, "payoff": 3, "anti_slop": 6, "zh_naturalness": 8,
            "total": 21, "fixes": ["lead with the number", "cut the last line"]}
    p = build_refine_prompt("原始草稿內容", crit, top_posts=[])
    assert "原始草稿內容" in p
    assert "lead with the number" in p
    assert "cut the last line" in p


def test_pick_better_returns_higher_scoring():
    original = ("orig text", {"total": 60})
    refined = ("refined text", {"total": 75})
    text, crit = pick_better(original, refined)
    assert text == "refined text"


def test_pick_better_prefers_original_on_tie_or_lower():
    original = ("orig", {"total": 70})
    refined = ("worse", {"total": 65})
    assert pick_better(original, refined)[0] == "orig"
    assert pick_better(("orig", {"total": 70}), ("ref", {"total": 70}))[0] == "orig"


def test_pick_better_handles_none_refined():
    original = ("orig", {"total": 55})
    assert pick_better(original, None)[0] == "orig"
