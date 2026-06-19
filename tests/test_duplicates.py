import json
from datetime import datetime, timezone

from orbit.db import DB
from orbit.duplicates import (
    canonicalize_url,
    check_duplicate,
    record_content,
    topic_fingerprint,
)


def _seed_draft(db: DB, *, content: str, source_url: str | None = None, source_links=None, status: str = "published") -> int:
    now = datetime.now(timezone.utc).isoformat()
    idea_id = db.conn["ideas"].insert({
        "title": content[:80],
        "source": "test",
        "status": "published",
        "created_at": now,
    }).last_pk
    draft_id = db.conn["drafts"].insert({
        "idea_id": idea_id,
        "platform": "threads",
        "content": content,
        "status": status,
        "source_url": source_url,
        "source_links": json.dumps(source_links or []),
        "created_at": now,
    }).last_pk
    return draft_id


def test_canonicalize_url_strips_tracking():
    assert canonicalize_url("https://example.com/a/?utm_source=x&tag=14&keep=1#frag") == (
        "https://example.com/a?keep=1"
    )


def test_topic_fingerprint_stable_for_same_product():
    first = topic_fingerprint("Anthropic launched Claude Code Loop and Goal", {})
    second = topic_fingerprint("Claude Code 的 Loop + Goal workflow 上線", {})
    assert "claude" in first
    assert "claude" in second
    assert first.split(":")[0] == second.split(":")[0]


def test_duplicate_blocks_same_canonical_link(orbit_home):
    db = DB(orbit_home)
    _seed_draft(
        db,
        content="有人開源了一套 Claude Code workflow。",
        source_links=["https://github.com/acme/agent-workflow?utm_source=x"],
    )
    decision = check_duplicate(
        db,
        content="Another post about the same repo",
        source={"source_links": ["https://github.com/acme/agent-workflow"]},
    )
    assert decision.is_duplicate
    assert decision.reason == "same canonical URL"


def test_duplicate_blocks_same_topic_from_different_sources(orbit_home):
    db = DB(orbit_home)
    draft_id = _seed_draft(
        db,
        content="有人開源了一套讓 Claude Code 持續學習的系統，叫 Hivemind。",
        source_url="https://x.com/a/status/1",
    )
    decision = check_duplicate(
        db,
        content="Hivemind lets Claude Code remember successful task paths across sessions.",
        source={"url": "https://x.com/b/status/2", "text": "Claude Code Hivemind memory system"},
    )
    assert decision.is_duplicate
    assert decision.matched_draft_id == draft_id
    assert (
        decision.reason == "same topic fingerprint"
        or decision.reason.startswith("same product/entity")
        or decision.reason.startswith("high lexical overlap")
    )


def test_same_product_different_news_is_not_duplicate(orbit_home):
    """Sharing a brand (e.g. Claude Code) is not enough to block.

    Keith wants topic overlap allowed — only near-identical news about the SAME
    thing should be caught. Two distinct Claude Code launches must both pass.
    """
    db = DB(orbit_home)
    # The real-world collision: an unrelated Chinese post about enterprises not
    # adopting agents, matched purely on the generic word "enterprise".
    _seed_draft(
        db,
        content="大部分企業不會用 Hermes 或 OpenClaw，因為安全問題。"
                "企業環境有 compliance、audit 的需求。Enterprise 風險太高。",
        source_url="https://x.com/keith/status/111",
    )
    decision = check_duplicate(
        db,
        content="New in Claude Code: Artifacts. Interactive pages built from your "
                "session, like a PR walkthrough, shared at a private link. "
                "Available in beta on Team and Enterprise plans.",
        source={"url": "https://x.com/claudeai/status/222",
                "text": "New in Claude Code: Artifacts interactive pages Enterprise"},
    )
    assert not decision.is_duplicate, (
        f"blocked as {decision.reason!r} — generic word overlap ('enterprise') "
        "between unrelated posts should not block"
    )


def test_same_product_same_news_still_blocked(orbit_home):
    """The guard must still catch the SAME launch described twice."""
    db = DB(orbit_home)
    _seed_draft(
        db,
        content="Claude Code 推出 Artifacts，把你的 session 變成可分享的互動頁面。",
        source_url="https://x.com/a/status/1",
    )
    decision = check_duplicate(
        db,
        content="New in Claude Code: Artifacts — interactive pages built from your "
                "session, shared with your team at a private link.",
        source={"url": "https://x.com/b/status/2",
                "text": "Claude Code Artifacts interactive pages session private link"},
    )
    assert decision.is_duplicate


def test_record_content_creates_ledger_match(orbit_home):
    db = DB(orbit_home)
    draft_id = _seed_draft(db, content="Some unrelated draft")
    record_content(
        db,
        draft_id=draft_id,
        content="Microsoft Copilot scheduled prompts are now live.",
        source={"tweet_id": "123", "url": "https://x.com/test/status/123"},
        status="scheduled",
    )
    decision = check_duplicate(
        db,
        content="Different wording",
        source={"tweet_id": "123", "url": "https://x.com/other/status/999"},
    )
    assert decision.is_duplicate
    assert decision.reason == "same source"
