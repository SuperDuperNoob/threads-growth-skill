from __future__ import annotations
from typing import Any
from orbit.profile import LANGUAGES, MARKET, VOICE_NAME


def extract_top_patterns(posts: list[dict[str, Any]], top_n: int = 10) -> list[dict[str, Any]]:
    scored = []
    for p in posts:
        views = p.get("views", 0) or 0
        likes = p.get("likes", 0) or 0
        scored.append({
            **p,
            "like_rate": round(likes / views * 100, 2) if views else 0.0,
        })
    return sorted(scored, key=lambda x: x["views"], reverse=True)[:top_n]


def build_pattern_prompt(
    top_posts: list[dict[str, Any]],
    bookmarks: list[dict[str, Any]],
    recent_topics: list[str] | None = None,
    recent_performance: dict[str, Any] | None = None,
    *,
    count: int = 3,
) -> str:
    examples = "\n\n---\n\n".join(
        f"[{p['views']:,} views, {p['like_rate']}% like rate]\n{p['content']}"
        for p in top_posts[:5]
    )
    source_limit = max(10, count + 4)
    sources = "\n\n---\n\n".join(
        f"Author: {b['author']}\nURL: {b['url']}\n{b['text']}"
        for b in bookmarks[:source_limit]
    )
    recent_section = "\n".join(f"- {t}" for t in (recent_topics or [])[:5]) or "(none — first post in this batch)"
    performance_section = _format_recent_performance(recent_performance)
    diversity_plan = _format_threads_diversity_plan(count)

    return f"""You are a top-tier Threads content creator in {MARKET}. Your job is to write {count} Threads posts.
LANGUAGE RULE (HARD): Publish ONLY in {' and '.join(LANGUAGES)}. Code-switch Malaysian Malay and English the way a real local tech/builder creator does (everyday Malay phrasing, English for technical terms, product names, and code concepts). Zero Chinese, zero Indonesian, zero other languages.

Your writing style — learned from your TOP PERFORMING posts:

{examples}

HARD CONSTRAINTS — every top-10 post follows these:

OPENING HOOK — code-switched MY+EN templates, weighted by like-rate performance:
  (a) "Ada orang [verb-ed] + named product" / "Someone just [verb-ed]" — TIER 1. Default opening. Pair with a distinctive named tool AND a clear payoff ("gila power", "tak payah pening kepala", "terus siap").
  (b) "[BrandName] [verb-ed]" — TIER 1 for views, but must clear the PAYOFF GATE. Bare announcements ("X launched Y") bomb.
  (c) "Satu [thing] [milestone]" — TIER 2. Use for genuine GitHub trending or milestone moments.
  (d) "Korang [pernah/tahu tak] [pain]?" — DEPRECATED. Diagnosed dead format. Default: SKIP (d) entirely.

PAYOFF GATE:
Posts that ONLY announce ("Brand X launched feature Y") are ignored. Posts that pair a tool with a sharp outcome clear 1.4%+:
  - a direct shortcut ("tak payah bayar bulanan" / "terus setup 10 minit" / "free je")
  - a distinctive named product worth trying (Removerized, Cal.diy, SkillOpt)
  - your own creator stake/POV ("aku test letak dalam Hermes", "susah payah aku code benda ni sekali orang lain open-source")
Before finalizing EACH draft, ask: "Stripped of the brand name, is there still a reason for a stranger to tap like?" If not, rewrite around the payoff.

AUDIENCE WIDTH:
The tool/insight in your draft must be relevant to a GENERAL AI/tech builder in Southeast Asia — not a narrow sub-niche. 

BODY MUST INCLUDE (HARD rules):
- At least ONE concrete number (GitHub stars, dollars saved, hours reduced, day-N counter). Vague "banyak/ramai" = REJECT.
- PREFER A DOLLAR OR RM FIGURE when the source has one ("Jimat $80k/tahun", "Buat RM10k sebulan").
- Open-source / free signal when applicable ("open-source", "free", "MIT", "fork").
- LAST LINE = direct reader BENEFIT or actionable closing, NOT a dead observation.
    ✓ "Tak payah bayar bulanan dah." / "Jimat 2 jam sehari." / "Set up dalam 10 minit."
    ✗ "Future of AI is here." / "Ini standard baru."

STYLE:
- Short, punchy sentences. Single line breaks between thoughts.
- Natural Malaysian Malay + English code-switch.
- No hashtags. No emojis unless very sparing.
- 150-300 characters total per part.

DO NOT WRITE:
- BARE PRODUCT ANNOUNCEMENTS without a payoff or your POV.
- Generic AI commentary ("Most people use AI like...").
- Posts whose last line is observational rather than actionable.

TOPIC FATIGUE GUARD:
Your most-recent posted topics (do NOT pick a source covering the same brand/cluster):
{recent_section}
If your draft would cover the same BRAND or same SEMANTIC CLUSTER as any item above, pick a different source. Algorithm suppresses consecutive-topic clustering (SKILL.md S5/S14).

SOURCE MATERIAL from X bookmarks (use 1-3 as inspiration):

{sources}

RECENT PERFORMANCE SIGNAL:
{performance_section}

VARIATION PLAN:
{diversity_plan}

Write exactly {count} Threads posts. Number them [1] through [{count}]. Each must use different source material. Across the batch, vary angle, first line, structure, emotional frame, and final reader benefit. Hook mix: prefer (a) and (b); use (c) only if a source genuinely is a milestone; SKIP (d). It is OK to reuse hook families when writing more drafts than allowed hook templates, but do not reuse the same opening rhythm or body structure. Apply the TOPIC FATIGUE GUARD before finalizing each. Output only the posts, no explanations."""


def _format_recent_performance(recent_performance: dict[str, Any] | None) -> str:
    if not recent_performance:
        return "(no recent performance data available)"
    sample_size = int(recent_performance.get("sample_size") or 0)
    if sample_size <= 0:
        return "(no recent performance data available)"
    baseline = float(recent_performance.get("baseline_like_rate") or 1.17)
    median = recent_performance.get("median_like_rate")
    below = int(recent_performance.get("below_baseline_count") or 0)
    weak = bool(recent_performance.get("weak_recent_performance"))
    lines = [
        f"Last {sample_size} Threads posts median like rate: {median:.2f}% vs {baseline:.2f}% baseline."
        if isinstance(median, (int, float))
        else f"Last {sample_size} Threads posts checked against {baseline:.2f}% baseline.",
        f"{below}/{sample_size} were below baseline.",
    ]
    if weak:
        lines.append("RECOVERY MODE is active: recent posts are underperforming.")

    examples = recent_performance.get("examples") or []
    if examples:
        lines.append("Recent weak-post openings to avoid mimicking:")
        for ex in examples[:3]:
            opening = (ex.get("opening") or "").strip()
            like_rate = ex.get("like_rate")
            if not opening:
                continue
            if isinstance(like_rate, (int, float)):
                lines.append(f"- {opening} ({like_rate:.2f}% like rate)")
            else:
                lines.append(f"- {opening}")
    return "\n".join(lines)


def _format_threads_diversity_plan(count: int) -> str:
    lanes = [
        "1. Tool utility: what this lets a general AI builder do faster today.",
        "2. Money/time saved: quantify the concrete cost or hours avoided.",
        "3. Open-source/fork angle: emphasize free, MIT, self-hosted, or GitHub momentum.",
        "4. Big-company launch angle: explain why a known brand's move changes workflow.",
        "5. Workflow before/after: show the old painful way vs new shortcut.",
        "6. Builder implication: concrete action readers should take this week.",
    ]
    selected = lanes[: max(1, min(count, len(lanes)))]
    if count > len(lanes):
        selected.extend(
            f"{i}. Fresh source angle: use a new source and avoid opening rhythm."
            for i in range(len(lanes) + 1, count + 1)
        )
    return "\n".join(selected)


def build_linkedin_prompt(bookmarks: list[dict[str, Any]], *, recent_formats: list[str] | None = None) -> str:
    """LinkedIn prompt adapted for MY+EN builder professional audience."""
    sources = "\n\n---\n\n".join(f"Author: {b['author']}\nURL: {b['url']}\n{b['text']}" for b in bookmarks[:10])
    return f"""You are a professional LinkedIn content writer in {MARKET}. Write 1 LinkedIn post in English (with natural local builder tone) for a tech founder/builder audience.
Sources:\n{sources}\nOutput only the post body."""


def classify_linkedin_format(content: str) -> str:
    return "STORY"


def _format_fatigue_block(recent_formats: list[str]) -> str:
    return ""


def build_facebook_variant_prompt(content: str, *, has_video: bool = False) -> str:
    return f"""Rewrite this Threads post as a Facebook discovery-feed post in Malaysian Malay/English.\nOriginal:\n{content}"""
