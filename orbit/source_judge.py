from __future__ import annotations
from typing import Any
import json


def build_source_judge_prompt(
    sources: list[dict[str, Any]],
    recent_topics: list[str] | None,
    top_posts: list[dict[str, Any]],
) -> str:
    """Pure prompt: score each source on novelty/width/fit. Returns a string.

    The LLM is asked to return a strict JSON array of objects keyed by the
    source's zero-based index so the caller can map results back positionally.
    """
    rendered = "\n\n---\n\n".join(
        f"[{i}] Author: {s.get('author')}\n{s.get('text', '')}"
        for i, s in enumerate(sources)
    )
    recent = "\n".join(f"- {t}" for t in (recent_topics or [])[:5]) or "(none)"
    winners = "\n".join(f"- {p['content'][:80]}" for p in top_posts[:5])
    return f"""You are ranking candidate source tweets for Keith's Threads posts.
His audience: general AI builders. His best posts (for reference):
{winners}

RECENTLY POSTED TOPICS — anything covering the same brand/product/cluster as
these is LOW novelty; penalize hard:
{recent}

Score EACH candidate 0-10 on three axes:
- novelty: is this a fresh topic vs the recently-posted list? (repeats = 0-3)
- audience_width: does a GENERAL AI builder care, or is it researcher-niche /
  narrow dev-tooling? (too niche = 0-3)
- brand_fit: is it in Keith's "practical AI tool/launch" lane?

CANDIDATES:
{rendered}

Return ONLY a JSON array, one object per candidate:
[{{"index": 0, "novelty": 8, "width": 7, "fit": 9, "reason": "..."}}]
No prose outside the JSON."""


def parse_source_judgment(raw: str) -> list[dict] | None:
    """Parse the judge's JSON array. Returns None on any failure (fail-open).

    Drops entries missing required numeric axes or the index, so a partial
    response still yields usable rankings.
    """
    if not raw:
        return None
    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        data = json.loads(raw[start:end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    clean = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            clean.append({
                "index": int(item["index"]),
                "novelty": float(item["novelty"]),
                "width": float(item["width"]),
                "fit": float(item["fit"]),
                "reason": str(item.get("reason", "")),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return clean or None


def rank_judged(judged: list[dict], *, novelty_weight: float = 1.5) -> list[dict]:
    """Sort judged sources by weighted total, novelty weighted up by default."""
    def total(j: dict) -> float:
        return j["novelty"] * novelty_weight + j["width"] + j["fit"]
    return sorted(judged, key=total, reverse=True)
