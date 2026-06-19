"""Tests for the in-session pure helpers in orbit.commands.draft."""
from datetime import datetime, timezone

from orbit.commands.draft import (
    _add_dismissed_source,
    _dismissed_source_keys,
    _parse_dismiss,
    _parse_picks,
    _parse_regenerate,
    _parse_tweak,
    _recent_threads_performance,
    _recent_threads_topics,
    _require_media_sources,
    _score_threads_draft_virality,
    _source_key,
)
from orbit.commands.drafts import _pick_comment_link, _pick_embed_url
from orbit.db import DB


# --- _parse_picks ---

def test_parse_picks_single():
    assert _parse_picks("1", 3) == [0]


def test_parse_picks_comma():
    assert _parse_picks("1,3", 3) == [0, 2]


def test_parse_picks_space():
    assert _parse_picks("1 3", 3) == [0, 2]


def test_parse_picks_comma_space():
    assert _parse_picks("1, 3", 3) == [0, 2]


def test_parse_picks_preserves_order():
    assert _parse_picks("3,1", 3) == [2, 0]


def test_parse_picks_dedupes():
    assert _parse_picks("1,1,3", 3) == [0, 2]


def test_parse_picks_rejects_words():
    assert _parse_picks("1 and 3", 3) == []


def test_parse_picks_empty():
    assert _parse_picks("", 3) == []


def test_parse_picks_out_of_range_dropped():
    # "5" is out of range; "1" is fine. Out-of-range items are silently dropped.
    assert _parse_picks("1,5", 3) == [0]


def test_parse_picks_zero_dropped():
    assert _parse_picks("0", 3) == []


# --- _parse_tweak ---

def test_parse_tweak_basic():
    assert _parse_tweak("t1 make it shorter", 3) == (0, "make it shorter")


def test_parse_tweak_no_space_after_t():
    # "t2 ..." form is canonical. "t 2 ..." should also work for forgiving typing.
    assert _parse_tweak("t 2 add a CTA", 3) == (1, "add a CTA")


def test_parse_tweak_multiline_feedback():
    raw = "t1 make it shorter\nand add a question"
    result = _parse_tweak(raw, 3)
    assert result is not None
    assert result[0] == 0
    assert "shorter" in result[1] and "question" in result[1]


def test_parse_tweak_returns_none_for_save_input():
    # Pure save selections should NOT be parsed as tweaks
    assert _parse_tweak("1,3", 3) is None
    assert _parse_tweak("1", 3) is None
    assert _parse_tweak("", 3) is None


def test_parse_tweak_rejects_no_feedback():
    # `t1` alone with no feedback is meaningless
    assert _parse_tweak("t1", 3) is None
    assert _parse_tweak("t1   ", 3) is None


def test_parse_tweak_rejects_out_of_range():
    assert _parse_tweak("t5 reword", 3) is None
    assert _parse_tweak("t0 reword", 3) is None


# --- _parse_regenerate ---

def test_parse_regenerate_all_bare_r():
    assert _parse_regenerate("r", 3) == [0, 1, 2]


def test_parse_regenerate_all_r_with_spaces():
    assert _parse_regenerate("  r  ", 3) == [0, 1, 2]


def test_parse_regenerate_single():
    assert _parse_regenerate("r1", 3) == [0]


def test_parse_regenerate_multi_comma():
    assert _parse_regenerate("r1,3", 3) == [0, 2]


def test_parse_regenerate_multi_space():
    assert _parse_regenerate("r 1 3", 3) == [0, 2]


def test_parse_regenerate_returns_none_for_save():
    assert _parse_regenerate("1", 3) is None
    assert _parse_regenerate("1,3", 3) is None


def test_parse_regenerate_returns_none_for_tweak():
    # 't1 shorter' looks like a tweak, not a regen
    assert _parse_regenerate("t1 shorter", 3) is None


def test_parse_regenerate_returns_none_for_empty():
    assert _parse_regenerate("", 3) is None


def test_parse_regenerate_returns_none_when_indices_invalid():
    # 'r5' — out of range, no valid pick parsed
    assert _parse_regenerate("r5", 3) is None


# --- _source_key ---

def test_source_key_uses_url_when_present():
    assert _source_key({"url": "https://x.com/foo/1", "text": "hi"}) == "url:https://x.com/foo/1"


def test_source_key_falls_back_to_text_hash():
    # Same text → same key. Different text → different key.
    a = _source_key({"text": "hello world"})
    b = _source_key({"text": "hello world"})
    c = _source_key({"text": "different"})
    assert a == b
    assert a != c
    assert a.startswith("text:")


def test_source_key_handles_empty_dict():
    # Empty / falsy source should produce a stable empty-key marker.
    assert _source_key({}) == ""


def test_source_key_url_takes_precedence_over_text():
    # Two sources with same URL but different text → same key.
    a = _source_key({"url": "https://x.com/x/1", "text": "A"})
    b = _source_key({"url": "https://x.com/x/1", "text": "B"})
    assert a == b


# --- _parse_dismiss ---

def test_parse_dismiss_all_bare_d():
    assert _parse_dismiss("d", 3) == [0, 1, 2]


def test_parse_dismiss_specific_index():
    assert _parse_dismiss("d1", 3) == [0]


def test_parse_dismiss_multi_comma():
    assert _parse_dismiss("d1,3", 3) == [0, 2]


def test_parse_dismiss_returns_none_for_save():
    assert _parse_dismiss("1", 3) is None


def test_parse_dismiss_returns_none_for_regen():
    assert _parse_dismiss("r1", 3) is None


def test_parse_dismiss_returns_none_for_tweak():
    assert _parse_dismiss("t1 shorter", 3) is None


def test_parse_dismiss_returns_none_when_out_of_range():
    assert _parse_dismiss("d5", 3) is None


# --- dismissed_sources persistence ---

def test_add_dismissed_source_persists_and_dedupes(orbit_home):
    db = DB(orbit_home)

    src = {"url": "https://x.com/foo/1", "text": "hello world"}
    assert _add_dismissed_source(db, src) is True   # newly added
    assert _add_dismissed_source(db, src) is False  # already there

    keys = _dismissed_source_keys(db)
    assert _source_key(src) in keys


def test_dismissed_source_keys_empty_on_fresh_db(orbit_home):
    db = DB(orbit_home)
    assert _dismissed_source_keys(db) == set()


def test_add_dismissed_source_skips_empty_key(orbit_home):
    db = DB(orbit_home)
    assert _add_dismissed_source(db, {}) is False
    assert _dismissed_source_keys(db) == set()


# --- _pick_comment_link ---

def test_pick_comment_link_prefers_github():
    links = '["https://example.com/blog", "https://github.com/org/repo"]'
    assert _pick_comment_link(links) == "GitHub: https://github.com/org/repo"


def test_pick_comment_link_falls_back_to_gitlab():
    links = '["https://example.com/blog", "https://gitlab.com/org/repo"]'
    assert _pick_comment_link(links) == "https://gitlab.com/org/repo"


def test_pick_comment_link_returns_none_for_no_forge():
    """Non-forge source links should still go as comments, not in the post body."""
    assert _pick_comment_link('["https://example.com/blog"]') == "https://example.com/blog"


def test_pick_comment_link_handles_empty_and_invalid():
    assert _pick_comment_link(None) is None
    assert _pick_comment_link("") is None
    assert _pick_comment_link("not json") is None
    assert _pick_comment_link("[]") is None


def test_pick_comment_link_keeps_github_label():
    links = '["https://example.com/blog", "https://github.com/org/repo"]'
    assert _pick_comment_link(links) == "GitHub: https://github.com/org/repo"


# --- media source requirement ---

def test_require_media_sources_filters_text_only_sources():
    media = {"text": "with media", "media_url": "https://pbs.twimg.com/media/a.jpg"}
    text_only = {"text": "without media"}
    assert _require_media_sources([text_only, media]) == [media]


def test_require_media_sources_returns_empty_when_no_media():
    # New contract: return the (empty) media-backed subset instead of raising,
    # so the caller can emit an empty JSON payload (Hermes) rather than crash.
    assert _require_media_sources([{"text": "without media"}]) == []


def test_require_media_sources_keeps_only_media_backed():
    sources = [
        {"text": "no media"},
        {"text": "has media", "media_url": "https://x.com/pic.jpg"},
    ]
    kept = _require_media_sources(sources)
    assert kept == [{"text": "has media", "media_url": "https://x.com/pic.jpg"}]


# --- virality score ---

def test_score_threads_draft_rewards_strong_media_ready_shape():
    draft = (
        "Google 剛開源了一個 26B 模型。\n\n"
        "Apache 2.0，單張 GPU 每秒 1,200 tokens。\n\n"
        "你今天就能省下推理成本。"
    )
    result = _score_threads_draft_virality(draft)
    assert result["score"] >= 80
    assert result["label"] == "high"


def test_score_threads_draft_penalizes_no_number_and_self_hook():
    result = _score_threads_draft_virality("我最近試了一個工具。\n\n感覺很不錯。")
    assert result["score"] < 65


# --- _pick_embed_url (Facebook link card) ---

def test_pick_embed_url_returns_github_raw():
    links = '["https://github.com/org/repo"]'
    assert _pick_embed_url(links) == "https://github.com/org/repo"


# --- _recent_threads_topics (topic-fatigue guard feed) ---

def _seed_threads_post(db: DB, *, content: str, published_at: str, ext_id: str) -> None:
    """Insert a published Threads post (draft + post row)."""
    idea_id = db.conn["ideas"].insert({
        "title": content[:80], "source": "sync", "status": "published",
        "created_at": published_at,
    }).last_pk
    draft_id = db.conn["drafts"].insert({
        "idea_id": idea_id, "platform": "threads", "content": content,
        "status": "published", "created_at": published_at,
    }).last_pk
    db.conn["posts"].insert({
        "draft_id": draft_id, "platform": "threads",
        "external_id": ext_id, "published_at": published_at,
    })


def _seed_threads_post_with_metrics(
    db: DB,
    *,
    content: str,
    published_at: str,
    ext_id: str,
    views: int,
    likes: int,
) -> None:
    """Insert a published Threads post with metrics."""
    idea_id = db.conn["ideas"].insert({
        "title": content[:80], "source": "sync", "status": "published",
        "created_at": published_at,
    }).last_pk
    draft_id = db.conn["drafts"].insert({
        "idea_id": idea_id, "platform": "threads", "content": content,
        "status": "published", "created_at": published_at,
    }).last_pk
    post_id = db.conn["posts"].insert({
        "draft_id": draft_id, "platform": "threads",
        "external_id": ext_id, "published_at": published_at,
    }).last_pk
    db.conn["metrics"].insert({
        "post_id": post_id,
        "platform": "threads",
        "views": views,
        "likes": likes,
        "comments": 0,
        "shares": 0,
        "reposts": 0,
        "clicks": 0,
        "saves": 0,
        "pulled_at": published_at,
    })


def test_recent_threads_topics_returns_in_descending_order(tmp_path):
    db = DB(home=tmp_path / ".orbit")
    _seed_threads_post(db, content="Oldest post", published_at="2026-05-30T01:00:00+00:00", ext_id="t1")
    _seed_threads_post(db, content="Middle post", published_at="2026-06-01T01:00:00+00:00", ext_id="t2")
    _seed_threads_post(db, content="Newest post", published_at="2026-06-03T01:00:00+00:00", ext_id="t3")

    topics = _recent_threads_topics(db, limit=5)
    assert topics == ["Newest post", "Middle post", "Oldest post"]


def test_recent_threads_topics_respects_limit(tmp_path):
    db = DB(home=tmp_path / ".orbit")
    for i in range(7):
        _seed_threads_post(
            db,
            content=f"Post {i}",
            published_at=f"2026-06-0{i+1}T01:00:00+00:00",
            ext_id=f"t{i}",
        )
    topics = _recent_threads_topics(db, limit=3)
    assert len(topics) == 3
    # Most recent first — Post 6, 5, 4
    assert topics[0] == "Post 6"


def test_recent_threads_topics_skips_unpublished(tmp_path):
    """A draft that was never posted (no posts row) shouldn't appear."""
    db = DB(home=tmp_path / ".orbit")
    _seed_threads_post(db, content="Posted", published_at="2026-06-01T01:00:00+00:00", ext_id="t1")
    # Unpublished draft: idea + draft rows but NO posts row
    idea_id = db.conn["ideas"].insert({
        "title": "Unposted", "source": "draft", "status": "draft",
        "created_at": "2026-06-02T01:00:00+00:00",
    }).last_pk
    db.conn["drafts"].insert({
        "idea_id": idea_id, "platform": "threads", "content": "Unposted",
        "status": "draft", "created_at": "2026-06-02T01:00:00+00:00",
    })

    topics = _recent_threads_topics(db)
    assert topics == ["Posted"]


def test_recent_threads_topics_returns_empty_list_on_fresh_db(tmp_path):
    db = DB(home=tmp_path / ".orbit")
    assert _recent_threads_topics(db) == []


def test_recent_threads_topics_truncates_long_content(tmp_path):
    """Long posts get truncated to 80 chars to keep prompt compact."""
    db = DB(home=tmp_path / ".orbit")
    long_content = "A" * 200
    _seed_threads_post(db, content=long_content, published_at="2026-06-01T01:00:00+00:00", ext_id="t1")
    topics = _recent_threads_topics(db)
    assert len(topics) == 1
    assert len(topics[0]) <= 80


def test_recent_threads_topics_strips_newlines(tmp_path):
    """Multi-line post content gets flattened so it reads as a single label."""
    db = DB(home=tmp_path / ".orbit")
    _seed_threads_post(
        db,
        content="Line one\n\nLine two\n\nLine three",
        published_at="2026-06-01T01:00:00+00:00",
        ext_id="t1",
    )
    topics = _recent_threads_topics(db)
    assert "\n" not in topics[0]
    assert "Line one" in topics[0] and "Line two" in topics[0]


# --- _recent_threads_performance ---

def test_recent_threads_performance_flags_weak_recent_posts(tmp_path):
    db = DB(home=tmp_path / ".orbit")
    _seed_threads_post_with_metrics(
        db,
        content="Weak one",
        published_at="2026-06-01T01:00:00+00:00",
        ext_id="p1",
        views=1000,
        likes=5,
    )
    _seed_threads_post_with_metrics(
        db,
        content="Weak two",
        published_at="2026-06-02T01:00:00+00:00",
        ext_id="p2",
        views=1000,
        likes=8,
    )
    _seed_threads_post_with_metrics(
        db,
        content="Strong one",
        published_at="2026-06-03T01:00:00+00:00",
        ext_id="p3",
        views=1000,
        likes=20,
    )

    summary = _recent_threads_performance(db, limit=7)
    assert summary["sample_size"] == 3
    assert summary["below_baseline_count"] == 2
    assert summary["weak_recent_performance"] is True
    assert summary["median_like_rate"] == 0.8
    assert summary["examples"][0]["opening"] == "Weak two"


def test_recent_threads_performance_returns_empty_without_metrics(tmp_path):
    db = DB(home=tmp_path / ".orbit")
    assert _recent_threads_performance(db) == {}
