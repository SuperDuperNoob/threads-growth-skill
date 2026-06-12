"""Integration: _backfill_threads_embeddings populates posts.embedding from drafts.content."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from orbit.commands.sync import _backfill_threads_embeddings
from orbit.db import DB
from orbit.embeddings import EMBEDDING_MODEL, unpack_embedding


def _seed_post(db: DB, *, content: str, ext_id: str) -> int:
    now = datetime.now(timezone.utc).isoformat()
    idea_id = db.conn["ideas"].insert({
        "title": content[:80], "source": "sync", "status": "published", "created_at": now,
    }).last_pk
    draft_id = db.conn["drafts"].insert({
        "idea_id": idea_id, "platform": "threads", "content": content,
        "status": "published", "created_at": now,
    }).last_pk
    return db.conn["posts"].insert({
        "draft_id": draft_id, "platform": "threads",
        "external_id": ext_id, "published_at": now,
    }).last_pk


def _fake_embed_response(n: int, dim: int = 4):
    return SimpleNamespace(
        data=[SimpleNamespace(embedding=[0.1 * (i + 1)] * dim) for i in range(n)]
    )


def test_backfill_embeds_only_posts_missing_an_embedding(tmp_path):
    db = DB(home=tmp_path / ".orbit")
    id1 = _seed_post(db, content="post one", ext_id="t1")
    id2 = _seed_post(db, content="post two", ext_id="t2")

    captured_inputs: list[list[str]] = []

    def fake_create(**kwargs):
        captured_inputs.append(kwargs["input"])
        return _fake_embed_response(len(kwargs["input"]))

    with patch("orbit.commands.sync.embed_texts") as mock_embed:
        # Reimplement embed_texts behavior using our fake client
        mock_embed.side_effect = lambda texts: [
            [0.1 * (i + 1)] * 4 for i in range(len(texts))
        ] if texts else []

        n = _backfill_threads_embeddings(db)

    assert n == 2
    # Both posts now have embeddings
    p1 = db.conn["posts"].get(id1)
    p2 = db.conn["posts"].get(id2)
    assert p1["embedding"] is not None
    assert p2["embedding"] is not None
    assert p1["embedding_model"] == EMBEDDING_MODEL
    decoded = unpack_embedding(p1["embedding"])
    assert len(decoded) == 4
    # float32 round-trip — assert approximate equality
    for v in decoded:
        assert abs(v - 0.1) < 1e-5

    # Second call should be a no-op — nothing to backfill
    with patch("orbit.commands.sync.embed_texts") as mock_embed2:
        n2 = _backfill_threads_embeddings(db)
    assert n2 == 0
    mock_embed2.assert_not_called()


def test_backfill_skips_posts_with_empty_draft_content(tmp_path):
    db = DB(home=tmp_path / ".orbit")
    _seed_post(db, content="real post", ext_id="t1")
    _seed_post(db, content="", ext_id="t2")  # empty content

    with patch("orbit.commands.sync.embed_texts") as mock_embed:
        mock_embed.side_effect = lambda texts: [[0.5] * 4 for _ in texts]
        n = _backfill_threads_embeddings(db)

    assert n == 1  # Only the post with real content


def test_backfill_re_embeds_when_model_changes(tmp_path):
    db = DB(home=tmp_path / ".orbit")
    pid = _seed_post(db, content="post one", ext_id="t1")
    # Pre-populate with a stale model name
    db.conn["posts"].update(pid, {
        "embedding": b"\x00" * 16,
        "embedding_model": "some-old-model",
    })

    with patch("orbit.commands.sync.embed_texts") as mock_embed:
        mock_embed.side_effect = lambda texts: [[0.7] * 4 for _ in texts]
        n = _backfill_threads_embeddings(db)

    assert n == 1
    p = db.conn["posts"].get(pid)
    assert p["embedding_model"] == EMBEDDING_MODEL
