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
