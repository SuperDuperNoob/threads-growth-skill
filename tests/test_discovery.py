"""Unit tests for the audience-fit scorer in orbit.discovery."""
from datetime import datetime, timedelta, timezone

from orbit.discovery import score_candidate
from orbit.commands.discover import _normalize_apify_item, select_autofill_sources
from orbit.db import DB


NOW = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)


def _candidate(text: str, **kwargs) -> dict:
    base = {
        "text": text,
        "source_likes": 0,
        "source_retweets": 0,
        "source_views": 0,
        "created_at": NOW.isoformat(),
        "url": "https://x.com/test/status/1",
    }
    base.update(kwargs)
    return base


def test_brand_name_ai_mention_scores():
    r = score_candidate(_candidate("Claude can now write better code"), now=NOW)
    assert r.score >= 12
    assert any("brand-name AI" in s for s in r.reasoning)


def test_multiple_brands_capped_at_30():
    text = "Claude vs OpenAI vs Codex vs Gemini vs Llama vs Mistral"
    r = score_candidate(_candidate(text), now=NOW)
    # 6 brands × 12 = 72, but capped at 30
    brand_delta = sum(int(s.split()[0][1:]) for s in r.reasoning if "brand-name" in s)
    assert brand_delta == 30


def test_open_source_signal_scores():
    r = score_candidate(_candidate("Just open sourced our entire framework. MIT license."), now=NOW)
    assert any("open-source" in s for s in r.reasoning)
    assert r.score >= 15


def test_viral_source_boost():
    r = score_candidate(_candidate(
        "Some tweet text",
        source_likes=12000,
        source_retweets=2000,
    ), now=NOW)
    assert any("viral source" in s for s in r.reasoning)
    assert r.score >= 15


def test_fresh_under_48h_boost():
    fresh = (NOW - timedelta(hours=12)).isoformat()
    r = score_candidate(_candidate("Anthropic launched something", created_at=fresh), now=NOW)
    assert any("fresh" in s for s in r.reasoning)


def test_stale_penalty():
    stale = (NOW - timedelta(days=30)).isoformat()
    r = score_candidate(_candidate("Old news about Claude", created_at=stale), now=NOW)
    assert any("stale" in s for s in r.reasoning)


def test_reply_penalized():
    r = score_candidate(_candidate("@someone interesting point about Claude"), now=NOW)
    assert any("reply" in s for s in r.reasoning)


def test_short_text_penalized():
    r = score_candidate(_candidate("Claude rocks!"), now=NOW)
    # short post penalty fires (< 40 chars)
    assert any("very short" in s for s in r.reasoning)


def test_novelty_penalty_on_repeated_topics():
    # Candidate mentions "presenton" — a brand-like distinctive token
    cand = _candidate("Presenton just launched a new feature")
    # Many recent posts about presenton → should penalize
    existing = [
        "Presenton 剛在 GitHub 上拿到 5,000+ 顆星",
        "Presenton 又出新功能",
        "用 Presenton 做簡報",
        "Presenton 的競爭對手",
    ]
    r_with_overlap = score_candidate(cand, existing_topics=existing, now=NOW)
    r_no_overlap = score_candidate(cand, existing_topics=[], now=NOW)
    # With overlap, score should be strictly lower
    assert r_with_overlap.score < r_no_overlap.score


def test_brand_names_dont_count_as_novelty_overlap():
    # Bug we fixed: Claude/Anthropic shouldn't trigger novelty penalty since
    # those names repeat across many legit posts on different topics.
    cand = _candidate("New Anthropic research on alignment via Claude")
    existing = [
        "Claude 又出新版本",
        "Anthropic 發表新論文",
        "用 Claude code 寫 react",
        "Anthropic 的 MCP 更新",
    ]
    r = score_candidate(cand, existing_topics=existing, now=NOW)
    assert not any("already covered" in s for s in r.reasoning), (
        f"Brand-name repetition should NOT trigger novelty penalty; got: {r.reasoning}"
    )


def test_score_clamped_0_100():
    # Pile on every positive signal
    text = "Anthropic just open sourced Claude Code — github.com/anthropic/claude-code, MIT license, free alternative to Cursor. Launching today!"
    r = score_candidate(_candidate(
        text,
        source_likes=50000,
        source_retweets=10000,
    ), now=NOW)
    assert 0 <= r.score <= 100


def test_empty_text_returns_zero():
    r = score_candidate(_candidate(""), now=NOW)
    assert r.score == 0


def test_curated_list_is_non_empty():
    """Sanity check: orbit.curated.ALL should have the accounts we configured."""
    from orbit.curated import ALL, OFFICIAL_AI_COMPANIES
    assert len(ALL) > 20
    assert "AnthropicAI" in OFFICIAL_AI_COMPANIES
    assert "AnthropicAI" in ALL


def test_normalize_apify_item_maps_common_fields():
    item = {
        "text": "Anthropic just launched a Claude Code feature",
        "userName": "AnthropicAI",
        "tweetUrl": "https://x.com/AnthropicAI/status/1",
        "tweetId": "1",
        "likeCount": 1200,
        "retweetCount": 200,
        "media": [{"url": "https://pbs.twimg.com/media/a.jpg", "type": "photo"}],
    }
    out = _normalize_apify_item(item)
    assert out["author"] == "@AnthropicAI"
    assert out["tweet_id"] == "1"
    assert out["source_likes"] == 1200
    assert out["media_url"] == "https://pbs.twimg.com/media/a.jpg"


def test_select_autofill_sources_requires_media_and_blocks_duplicates(orbit_home):
    db = DB(orbit_home)
    now = datetime.now(timezone.utc).isoformat()
    idea_id = db.conn["ideas"].insert({
        "title": "Claude Code Hivemind",
        "source": "test",
        "status": "published",
        "created_at": now,
    }).last_pk
    db.conn["drafts"].insert({
        "idea_id": idea_id,
        "platform": "threads",
        "content": "有人開源了一套讓 Claude Code 持續學習的系統，叫 Hivemind。",
        "status": "published",
        "created_at": now,
    })
    candidates = [
        _candidate(
            "Anthropic just launched Claude Code Hivemind memory for agents",
            url="https://x.com/a/status/1",
            created_at=now,
            media_url="https://pbs.twimg.com/media/dup.jpg",
            media_type="photo",
            source_likes=2000,
        ),
        _candidate(
            "OpenAI just launched a free Codex workflow for agent builders",
            url="https://x.com/b/status/2",
            created_at=now,
            media_url=None,
            media_type=None,
            source_likes=2000,
        ),
        _candidate(
            "Google just launched Gemini agent skills for builders",
            url="https://x.com/c/status/3",
            created_at=now,
            media_url="https://pbs.twimg.com/media/gemini.jpg",
            media_type="photo",
            source_likes=2000,
        ),
    ]
    selected = select_autofill_sources(db, candidates, min_score=35, count=3)
    assert [s["url"] for s in selected] == ["https://x.com/c/status/3"]
