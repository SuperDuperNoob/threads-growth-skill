from orbit.analysis import extract_top_patterns

SAMPLE_POSTS = [
    {"content": "有人剛剛做了X\n\n結果很驚人\n\n...", "views": 19000, "likes": 319},
    {"content": "我用了Hermes第15天。\n\n今天發現...", "views": 11000, "likes": 111},
    {"content": "一家公司超越了OpenAI。\n\n由他們放走的女人創立。", "views": 13000, "likes": 174},
    {"content": "你有沒有試過X？\n\n問題在於...\n\n解法是...", "views": 10000, "likes": 167},
    {"content": "短文", "views": 100, "likes": 2},
]

def test_returns_top_posts():
    patterns = extract_top_patterns(SAMPLE_POSTS, top_n=3)
    assert len(patterns) == 3

def test_sorted_by_views():
    patterns = extract_top_patterns(SAMPLE_POSTS, top_n=3)
    views = [p["views"] for p in patterns]
    assert views == sorted(views, reverse=True)

def test_includes_required_fields():
    patterns = extract_top_patterns(SAMPLE_POSTS, top_n=2)
    for p in patterns:
        assert "content" in p
        assert "views" in p
        assert "likes" in p
        assert "like_rate" in p

def test_handles_zero_views():
    posts = [{"content": "test", "views": 0, "likes": 5}]
    patterns = extract_top_patterns(posts, top_n=1)
    assert patterns[0]["like_rate"] == 0.0

def test_build_pattern_prompt_contains_examples():
    from orbit.analysis import build_pattern_prompt
    posts = [{"content": "test post", "views": 1000, "likes": 10, "like_rate": 1.0}]
    bookmarks = [{"text": "bookmark text", "author": "@user", "url": "https://x.com/user/1"}]
    prompt = build_pattern_prompt(posts, bookmarks)
    assert "test post" in prompt
    assert "bookmark text" in prompt
    assert "[1]" in prompt  # numbered drafts instruction


def test_build_pattern_prompt_embeds_recent_topics_for_fatigue_guard():
    from orbit.analysis import build_pattern_prompt
    posts = [{"content": "p", "views": 1, "likes": 0, "like_rate": 0.0}]
    bookmarks = [{"text": "b", "author": "@u", "url": "https://x.com/u/1"}]
    recent = [
        "Google 剛推出了 Gemini Spark",
        "有人剛剛開源了 Cal.com fork",
        "Anthropic Frontend Design skill",
    ]
    prompt = build_pattern_prompt(posts, bookmarks, recent_topics=recent)
    assert "TOPIC FATIGUE GUARD" in prompt
    for topic in recent:
        assert topic in prompt


def test_build_pattern_prompt_handles_no_recent_topics():
    """Backwards compat: when recent_topics is omitted/None, prompt still builds
    and shows a sane placeholder rather than an empty section."""
    from orbit.analysis import build_pattern_prompt
    posts = [{"content": "p", "views": 1, "likes": 0, "like_rate": 0.0}]
    bookmarks = [{"text": "b", "author": "@u", "url": "https://x.com/u/1"}]
    # No recent_topics arg at all — proves the kwarg has a working default
    prompt = build_pattern_prompt(posts, bookmarks)
    assert "TOPIC FATIGUE GUARD" in prompt
    assert "none — first post in this batch" in prompt


def test_build_pattern_prompt_deprecates_template_d():
    """Slump-recovery rule: template (d) should be marked DEPRECATED, not just sparing."""
    from orbit.analysis import build_pattern_prompt
    posts = [{"content": "p", "views": 1, "likes": 0, "like_rate": 0.0}]
    bookmarks = [{"text": "b", "author": "@u", "url": "https://x.com/u/1"}]
    prompt = build_pattern_prompt(posts, bookmarks)
    assert "DEPRECATED" in prompt
    assert "SKIP (d)" in prompt or "skip (d)" in prompt.lower()


def test_build_pattern_prompt_includes_bare_announcement_payoff_gate():
    """Slump-recovery 2026-06-19: pure 'Brand launched X' announcements collapsed
    to 0-0.06% like rate. The prompt must demote the bare-announcement shape and
    require a concrete payoff/POV before the announcement counts."""
    from orbit.analysis import build_pattern_prompt
    posts = [{"content": "p", "views": 1, "likes": 0, "like_rate": 0.0}]
    bookmarks = [{"text": "b", "author": "@u", "url": "https://x.com/u/1"}]
    prompt = build_pattern_prompt(posts, bookmarks)
    assert "PAYOFF GATE" in prompt
    # The dead pattern must be named in DO NOT WRITE.
    assert "announcement" in prompt.lower()


def test_build_pattern_prompt_includes_audience_width_rule():
    from orbit.analysis import build_pattern_prompt
    posts = [{"content": "p", "views": 1, "likes": 0, "like_rate": 0.0}]
    bookmarks = [{"text": "b", "author": "@u", "url": "https://x.com/u/1"}]
    prompt = build_pattern_prompt(posts, bookmarks)
    assert "AUDIENCE WIDTH" in prompt
    assert "general AI builder" in prompt or "anyone building with AI" in prompt


def test_build_pattern_prompt_includes_recent_performance_recovery_mode():
    from orbit.analysis import build_pattern_prompt
    posts = [{"content": "p", "views": 1, "likes": 0, "like_rate": 0.0}]
    bookmarks = [{"text": "b", "author": "@u", "url": "https://x.com/u/1"}]
    prompt = build_pattern_prompt(
        posts,
        bookmarks,
        recent_performance={
            "sample_size": 3,
            "baseline_like_rate": 1.17,
            "median_like_rate": 0.8,
            "below_baseline_count": 2,
            "weak_recent_performance": True,
            "examples": [{"opening": "Weak opener", "like_rate": 0.5}],
        },
    )
    assert "RECENT PERFORMANCE SIGNAL" in prompt
    assert "RECOVERY MODE is active" in prompt
    assert "Weak opener" in prompt


def test_build_pattern_prompt_for_six_drafts_uses_diversity_lanes():
    from orbit.analysis import build_pattern_prompt
    posts = [{"content": "p", "views": 1, "likes": 0, "like_rate": 0.0}]
    bookmarks = [{"text": "b", "author": "@u", "url": "https://x.com/u/1"}]
    prompt = build_pattern_prompt(posts, bookmarks, count=6)
    assert "VARIATION PLAN" in prompt
    assert "1. Tool utility" in prompt
    assert "6. Builder implication" in prompt
    assert "It is OK to reuse hook families" in prompt
