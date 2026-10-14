"""Embedding-based bookmark selection.

Used by `orbit draft` to pick the bookmarks most similar to Keith's top-performing
Threads posts, rather than slicing the first 10 in arrival order.

- Model: OpenAI text-embedding-3-large (3072 dims). Strong on Chinese+English mix.
- Storage: each post's vector is packed via struct and stored as BLOB on posts.embedding.
- Scoring: cosine similarity. Bookmark score = MAX similarity across the top-N winners.
  ("This bookmark looks like the most-viral thing it resembles" — single best match wins.)
"""
from __future__ import annotations

import math
import os
import struct
from typing import Iterable, Sequence

EMBEDDING_MODEL = "text-embedding-3-large"
EMBEDDING_DIM = 3072


def pack_embedding(vec: Sequence[float]) -> bytes:
    """Pack a float vector for SQLite BLOB storage."""
    return struct.pack(f"{len(vec)}f", *vec)


def unpack_embedding(blob: bytes) -> list[float]:
    """Unpack a BLOB back to a float list. Returns [] for empty/None input."""
    if not blob:
        return []
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity in [-1, 1]. Returns 0.0 if either vector is zero/empty."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def embed_texts(texts: Sequence[str], *, client=None) -> list[list[float]]:
    """Embed a list of strings with OpenAI text-embedding-3-large.

    Pass `client` for tests. In production, an OpenAI() client is created lazily so
    that imports don't fail when OPENAI_API_KEY isn't set (e.g. during pytest collect).

    Empty strings get an empty vector back rather than calling the API — text-embedding-3
    rejects empty input with a 400.
    """
    if not texts:
        return []

    # Map indices: only non-empty texts go to the API; empties get [] back.
    payload: list[str] = []
    payload_idx: list[int] = []
    for i, t in enumerate(texts):
        if t and t.strip():
            payload.append(t)
            payload_idx.append(i)

    if not payload:
        return [[] for _ in texts]

    if client is None:
        from openai import OpenAI
        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("CUSTOM_API_KEY") or "local"
        base_url = os.environ.get("OPENAI_BASE_URL") or "http://127.0.0.1:20128/v1"
        client = OpenAI(api_key=api_key, base_url=base_url)

    resp = client.embeddings.create(model=EMBEDDING_MODEL, input=payload)
    vectors_by_idx: dict[int, list[float]] = {
        payload_idx[i]: list(d.embedding) for i, d in enumerate(resp.data)
    }
    return [vectors_by_idx.get(i, []) for i in range(len(texts))]


def score_bookmarks_by_winners(
    bookmark_vectors: list[list[float]],
    winner_vectors: list[list[float]],
) -> list[float]:
    """Score each bookmark by its MAX cosine similarity to any winner.

    Returns one float per bookmark. Bookmarks with empty vectors get 0.0.
    Winners with empty vectors are ignored (so a partial backfill still works).
    """
    valid_winners = [w for w in winner_vectors if w]
    if not valid_winners:
        return [0.0] * len(bookmark_vectors)
    scores: list[float] = []
    for bv in bookmark_vectors:
        if not bv:
            scores.append(0.0)
            continue
        scores.append(max(cosine_similarity(bv, wv) for wv in valid_winners))
    return scores


DUPLICATE_SIMILARITY_THRESHOLD = 0.75
"""Cosine similarity above this means a bookmark is "about the same news item"
as an already-published post. Tuned against Keith's actual TC+English mix:
- 0.92 = same news item, slightly different prose (clear duplicate)
- 0.76 = same product launch covered slightly differently (still duplicate)
- 0.59 = same brand, different product (NOT a duplicate)
Sitting at 0.75 catches the 0.76-class case while keeping the brand-overlap
class through to the LLM, which can decide whether to use a different angle."""


def filter_duplicates(
    bookmarks: list[dict],
    bookmark_vectors: list[list[float]],
    published_vectors: list[list[float]],
    threshold: float = DUPLICATE_SIMILARITY_THRESHOLD,
) -> tuple[list[dict], list[list[float]], list[dict]]:
    """Drop bookmarks whose max similarity to any published post exceeds `threshold`.

    Returns (kept_bookmarks, kept_vectors, dropped_bookmarks). The dropped list
    is for logging — surfacing what got filtered helps users understand why a
    bookmark they expected to see is missing, and lets us catch threshold
    miscalibration early.

    No-ops cleanly when `published_vectors` is empty (fresh DB) — returns all
    bookmarks unchanged.
    """
    valid_published = [p for p in published_vectors if p]
    if not valid_published:
        return list(bookmarks), list(bookmark_vectors), []

    kept_bookmarks: list[dict] = []
    kept_vectors: list[list[float]] = []
    dropped: list[dict] = []
    for bookmark, bv in zip(bookmarks, bookmark_vectors):
        if not bv:
            # No embedding for this bookmark — can't compare, keep it.
            kept_bookmarks.append(bookmark)
            kept_vectors.append(bv)
            continue
        max_sim = max(cosine_similarity(bv, pv) for pv in valid_published)
        if max_sim >= threshold:
            dropped.append({**bookmark, "_dup_score": round(max_sim, 4)})
        else:
            kept_bookmarks.append(bookmark)
            kept_vectors.append(bv)
    return kept_bookmarks, kept_vectors, dropped


def rank_bookmarks(
    bookmarks: list[dict],
    bookmark_vectors: list[list[float]],
    winner_vectors: list[list[float]],
    top_k: int = 10,
) -> list[dict]:
    """Return the top_k bookmarks ranked by similarity to winners.

    Adds a `_score` field on each returned bookmark for debuggability / logging.
    Preserves original ordering as the tiebreaker.
    """
    scores = score_bookmarks_by_winners(bookmark_vectors, winner_vectors)
    enriched = [
        {**b, "_score": round(s, 4)} for b, s in zip(bookmarks, scores)
    ]
    # Stable sort: Python's sorted is stable, so original order breaks score ties.
    enriched.sort(key=lambda b: b["_score"], reverse=True)
    return enriched[:top_k]
