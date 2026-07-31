from __future__ import annotations
import json
from typing import Any

_AXES = ("hook", "payoff", "anti_slop", "zh_naturalness")


def build_critic_prompt(draft: str, top_posts: list[dict[str, Any]]) -> str:
    ref = "\n".join(f"- {p['content'][:80]}" for p in (top_posts or [])[:3])
    return f"""You grade a single Threads draft for Keith (audience: AI builders).
Reference winners:
{ref or "(none)"}

Grade the draft 0-10 on FOUR axes:
- hook: does line 1 lead with a surprising, concrete result? ("有人 + verb + named tool")
- payoff: does the LAST line deliver a reader benefit, not a flat observation?
- anti_slop: does it read human-written, or like template-filled AI slop?
- chinese (zh_naturalness): is it native Traditional Chinese, not translated-from-English calques?

DRAFT:
{draft}

Return ONLY JSON:
{{"hook":N,"payoff":N,"anti_slop":N,"zh_naturalness":N,"total":N,"fixes":["specific fix", ...]}}
`fixes` = concrete, minimal edits to raise the lowest axes. No prose outside JSON."""


def parse_critique(raw: str) -> dict | None:
    """Parse critic JSON. None on failure or any missing axis (fail-open)."""
    if not raw:
        return None
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        data = json.loads(raw[start:end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        scores = {axis: float(data[axis]) for axis in _AXES}
    except (KeyError, TypeError, ValueError):
        return None
    total = data.get("total")
    try:
        total = float(total)
    except (TypeError, ValueError):
        total = sum(scores.values())
    fixes = data.get("fixes") or []
    if not isinstance(fixes, list):
        fixes = []
    return {**scores, "total": total, "fixes": [str(f) for f in fixes]}


def build_refine_prompt(draft: str, critique: dict, top_posts: list[dict[str, Any]]) -> str:
    fixes = "\n".join(f"- {f}" for f in critique.get("fixes", [])) or "- tighten the hook and payoff"
    ref = "\n".join(f"- {p['content'][:80]}" for p in (top_posts or [])[:3])
    return f"""Rewrite this Threads draft addressing ONLY these critic fixes:
{fixes}

Preserve what already works. Keep it Traditional Chinese, under 500 chars,
same core topic. Reference winners for tone:
{ref or "(none)"}

ORIGINAL DRAFT:
{draft}

Return ONLY the rewritten draft text. No preamble, no JSON, no commentary."""


def pick_better(
    original: tuple[str, dict],
    refined: tuple[str, dict] | None,
) -> tuple[str, dict]:
    """Keep whichever draft scores higher. Refine must STRICTLY beat original.

    Each arg is (text, critique_dict). `refined` may be None (refine skipped or
    failed) -> original wins. This is the guardrail against reward-gaming: the
    refiner's own opinion never counts, only the re-graded critic total.
    """
    if refined is None:
        return original
    if refined[1].get("total", 0) > original[1].get("total", 0):
        return refined
    return original
