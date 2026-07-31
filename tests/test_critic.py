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
