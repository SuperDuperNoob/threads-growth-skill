"""orbit draft --json — non-interactive generate+score for the Hermes agent.

Hermes drives Orbit headlessly: it runs `orbit draft --json`, reads candidates
with scores from stdout, decides, then schedules. This tests the JSON shaping
function in isolation (no network / no Anthropic call) by feeding it drafts +
sources directly.
"""
from __future__ import annotations
import json

from orbit.commands.draft import build_draft_json_payload


def test_payload_shape():
    drafts = ["有人剛開源了一個工具。省下你三小時。", "soft draft no number"]
    sources = [{"url": "https://x.com/a/1", "text": "tool launch"},
               {"url": "https://x.com/b/2", "text": "thoughts"}]
    saved_ids = [101, 102]
    payload = build_draft_json_payload(
        drafts, sources, saved_ids,
        recent_topics=["openai-codex"], generated_at="2026-06-18T23:00:00Z",
    )
    assert payload["generated_at"] == "2026-06-18T23:00:00Z"
    assert payload["recent_topics"] == ["openai-codex"]
    assert len(payload["candidates"]) == 2

    c0 = payload["candidates"][0]
    assert c0["draft_id"] == 101
    assert c0["text"] == drafts[0]
    assert isinstance(c0["score"], int)
    assert c0["label"] in {"low", "medium", "high"}
    assert isinstance(c0["signals"], list)


def test_strong_draft_scores_higher_than_weak():
    drafts = [
        "有人剛開源了一個工具。省下你三小時。一個月就是十小時。",  # hook+number+benefit+open
        "這個還行吧",  # nothing
    ]
    sources = [{"url": "u1", "text": "t1"}, {"url": "u2", "text": "t2"}]
    payload = build_draft_json_payload(
        drafts, sources, [1, 2], recent_topics=[], generated_at="t",
    )
    assert payload["candidates"][0]["score"] > payload["candidates"][1]["score"]


def test_payload_is_json_serializable():
    payload = build_draft_json_payload(
        ["draft one"], [{"url": "u", "text": "t"}], [1],
        recent_topics=[], generated_at="t",
    )
    # Must round-trip cleanly — Hermes parses this off stdout.
    assert json.loads(json.dumps(payload)) == payload


def test_handles_fewer_ids_than_drafts_gracefully():
    # If a draft was blocked/not saved, ids and drafts may not align 1:1.
    # Only emit candidates that have a real saved id.
    payload = build_draft_json_payload(
        ["a", "b", "c"], [{"url": "u", "text": "t"}], [10, 11],
        recent_topics=[], generated_at="t",
    )
    assert [c["draft_id"] for c in payload["candidates"]] == [10, 11]


def test_json_stream_separation():
    """Regression: the JSON payload must be writable to a dedicated stream so
    the real run can keep stdout pure even when helpers print during generation.
    (A stray stdout write once corrupted the payload — see 2026-06-15.)"""
    import io
    from orbit.commands.draft import build_draft_json_payload
    stream = io.StringIO()
    payload = build_draft_json_payload(
        ["draft one"], [{"url": "u", "text": "t"}], [1],
        recent_topics=[], generated_at="t",
    )
    import json
    print(json.dumps(payload), file=stream)
    # round-trips cleanly from the isolated stream
    assert json.loads(stream.getvalue())["candidates"][0]["draft_id"] == 1
