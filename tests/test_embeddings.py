"""Tests for orbit.embeddings — pure functions + injected OpenAI client."""
from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from orbit.embeddings import (
    DUPLICATE_SIMILARITY_THRESHOLD,
    EMBEDDING_MODEL,
    cosine_similarity,
    embed_texts,
    filter_duplicates,
    pack_embedding,
    rank_bookmarks,
    score_bookmarks_by_winners,
    unpack_embedding,
)


def test_pack_unpack_roundtrip_preserves_values():
    vec = [0.1, -0.5, 1.0, 0.0, 0.333]
    blob = pack_embedding(vec)
    out = unpack_embedding(blob)
    assert len(out) == len(vec)
    for a, b in zip(vec, out):
        assert math.isclose(a, b, rel_tol=1e-5, abs_tol=1e-6)


def test_unpack_handles_empty_and_none():
    assert unpack_embedding(b"") == []
    assert unpack_embedding(None) == []  # type: ignore[arg-type]


def test_cosine_identical_vectors_is_one():
    v = [1.0, 2.0, 3.0]
    assert math.isclose(cosine_similarity(v, v), 1.0, abs_tol=1e-9)


def test_cosine_orthogonal_vectors_is_zero():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_cosine_handles_empty_and_mismatched_lengths():
    assert cosine_similarity([], [1.0]) == 0.0
    assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_score_uses_max_across_winners_not_average():
    # Bookmark perfectly matches one winner, orthogonal to the other.
    # MAX gives 1.0; mean would give 0.5. Confirms we use MAX.
    bookmark = [1.0, 0.0]
    winners = [[1.0, 0.0], [0.0, 1.0]]
    scores = score_bookmarks_by_winners([bookmark], winners)
    assert math.isclose(scores[0], 1.0, abs_tol=1e-9)


def test_score_ignores_empty_winners():
    # Partial backfill: some winners have no embedding yet — those are skipped.
    bookmark = [1.0, 0.0]
    winners = [[], [1.0, 0.0], []]
    scores = score_bookmarks_by_winners([bookmark], winners)
    assert math.isclose(scores[0], 1.0, abs_tol=1e-9)


def test_score_returns_zero_when_no_valid_winners():
    scores = score_bookmarks_by_winners([[1.0, 0.0]], [[], []])
    assert scores == [0.0]


def test_rank_bookmarks_sorts_by_score_and_caps_at_top_k():
    # Winner is purely along the x-axis. Bookmark vectors increasingly tilt
    # toward the y-axis, so similarity should strictly decrease 0 → 1 → 2.
    bookmarks = [
        {"text": "best"},   # parallel to winner → cos = 1
        {"text": "okay"},   # 45° from winner → cos ≈ 0.707
        {"text": "bad"},    # orthogonal to winner → cos = 0
    ]
    vectors = [
        [1.0, 0.0],
        [1.0, 1.0],
        [0.0, 1.0],
    ]
    winners = [[1.0, 0.0]]
    ranked = rank_bookmarks(bookmarks, vectors, winners, top_k=2)
    assert len(ranked) == 2
    assert ranked[0]["text"] == "best"
    assert ranked[1]["text"] == "okay"
    # _score attached and strictly ordered
    assert "_score" in ranked[0]
    assert ranked[0]["_score"] > ranked[1]["_score"]


def test_rank_bookmarks_preserves_original_order_on_ties():
    bookmarks = [{"text": "first"}, {"text": "second"}, {"text": "third"}]
    # All vectors identical → all tied → stable sort keeps original order
    vectors = [[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]]
    winners = [[1.0, 0.0]]
    ranked = rank_bookmarks(bookmarks, vectors, winners, top_k=3)
    assert [b["text"] for b in ranked] == ["first", "second", "third"]


def test_embed_texts_skips_empty_strings_without_calling_api():
    # If all inputs are empty, no API call should fire.
    called = []
    fake_client = SimpleNamespace(
        embeddings=SimpleNamespace(
            create=lambda **kw: (called.append(kw) or SimpleNamespace(data=[]))
        )
    )
    out = embed_texts(["", "   ", ""], client=fake_client)
    assert out == [[], [], []]
    assert called == []


def test_embed_texts_returns_vector_per_input_preserving_order():
    # Mix of empty + real strings — real ones get vectors, empties stay [].
    fake_data = [
        SimpleNamespace(embedding=[0.1, 0.2]),
        SimpleNamespace(embedding=[0.3, 0.4]),
    ]
    fake_client = SimpleNamespace(
        embeddings=SimpleNamespace(create=lambda **kw: SimpleNamespace(data=fake_data))
    )
    out = embed_texts(["real one", "", "another real"], client=fake_client)
    assert out == [[0.1, 0.2], [], [0.3, 0.4]]


def test_embed_texts_passes_correct_model():
    captured: dict = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(embedding=[1.0])])

    fake_client = SimpleNamespace(embeddings=SimpleNamespace(create=fake_create))
    embed_texts(["hello"], client=fake_client)
    assert captured["model"] == EMBEDDING_MODEL
    assert captured["input"] == ["hello"]


# --- filter_duplicates ---

def test_filter_duplicates_drops_high_similarity_bookmarks():
    # Bookmark 0 is identical to published[0] (sim = 1.0) → drop.
    # Bookmark 1 is orthogonal to all published → keep.
    bookmarks = [{"text": "dup"}, {"text": "fresh"}]
    bookmark_vectors = [[1.0, 0.0], [0.0, 1.0]]
    published_vectors = [[1.0, 0.0]]
    kept, kept_vecs, dropped = filter_duplicates(
        bookmarks, bookmark_vectors, published_vectors, threshold=0.80
    )
    assert [b["text"] for b in kept] == ["fresh"]
    assert kept_vecs == [[0.0, 1.0]]
    assert len(dropped) == 1
    assert dropped[0]["text"] == "dup"
    assert dropped[0]["_dup_score"] == 1.0


def test_filter_duplicates_keeps_all_when_no_published_vectors():
    # Fresh DB case — nothing published yet, nothing to dedup against.
    bookmarks = [{"text": "a"}, {"text": "b"}]
    bookmark_vectors = [[1.0, 0.0], [0.0, 1.0]]
    kept, kept_vecs, dropped = filter_duplicates(bookmarks, bookmark_vectors, [])
    assert kept == bookmarks
    assert kept_vecs == bookmark_vectors
    assert dropped == []


def test_filter_duplicates_keeps_all_when_published_have_no_embeddings():
    # Partial backfill — published exist but have no vectors. Should no-op.
    bookmarks = [{"text": "a"}]
    bookmark_vectors = [[1.0, 0.0]]
    published_vectors: list[list[float]] = [[]]
    kept, kept_vecs, dropped = filter_duplicates(bookmarks, bookmark_vectors, published_vectors)
    assert kept == bookmarks
    assert dropped == []


def test_filter_duplicates_keeps_bookmark_with_no_embedding():
    # Bookmark itself failed to embed (empty vector) — can't compare, keep it.
    bookmarks = [{"text": "no-embed"}, {"text": "dup"}]
    bookmark_vectors: list[list[float]] = [[], [1.0, 0.0]]
    published_vectors = [[1.0, 0.0]]
    kept, kept_vecs, dropped = filter_duplicates(
        bookmarks, bookmark_vectors, published_vectors, threshold=0.80
    )
    assert [b["text"] for b in kept] == ["no-embed"]
    assert [b["text"] for b in dropped] == ["dup"]


def test_filter_duplicates_respects_threshold():
    # Bookmark sim ≈ 0.71 to published. At threshold 0.80, kept; at 0.50, dropped.
    bookmarks = [{"text": "partial"}]
    bookmark_vectors = [[1.0, 1.0]]  # 45° to published
    published_vectors = [[1.0, 0.0]]
    # cos = 1/sqrt(2) ≈ 0.707

    kept_high, _, dropped_high = filter_duplicates(
        bookmarks, bookmark_vectors, published_vectors, threshold=0.80
    )
    assert len(kept_high) == 1
    assert dropped_high == []

    kept_low, _, dropped_low = filter_duplicates(
        bookmarks, bookmark_vectors, published_vectors, threshold=0.50
    )
    assert kept_low == []
    assert len(dropped_low) == 1


def test_filter_duplicates_uses_max_across_published_not_average():
    # One of the published is identical → should drop even though the other is orthogonal.
    bookmarks = [{"text": "x"}]
    bookmark_vectors = [[1.0, 0.0]]
    published_vectors = [[0.0, 1.0], [1.0, 0.0]]  # second one is identical
    kept, _, dropped = filter_duplicates(
        bookmarks, bookmark_vectors, published_vectors, threshold=0.80
    )
    assert kept == []
    assert dropped[0]["_dup_score"] == 1.0


def test_duplicate_threshold_default_is_tuned():
    # Sanity-check on the tunable constant — should be in a reasonable band.
    # Below 0.65 = too aggressive (catches same-topic but different news).
    # Above 0.90 = too loose (lets near-paraphrases through).
    assert 0.70 <= DUPLICATE_SIMILARITY_THRESHOLD <= 0.90
