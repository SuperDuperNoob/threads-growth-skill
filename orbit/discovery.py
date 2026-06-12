"""Audience-fit scoring for X tweet candidates.

Scoring is feature-based (not LLM-based) so it's fast, deterministic, and easy
to tune. Derived from analysis of Keith's top 10 vs bottom 5 Threads posts: the
combination of brand-name AI co + open-source signal + freshness dominates.

Each feature contributes a weighted point delta. Total is clamped 0-100. The
`explain()` helper returns the same reasoning the scorer used.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable


# Brand-name AI companies / products. Lowercased substring matches on tweet text.
AI_BRANDS = [
    # AI labs (every top-10 post mentioned at least one)
    "claude", "anthropic", "openai", "chatgpt", "codex", "gpt-4", "gpt-5",
    "google deepmind", "gemini", "meta ai", "llama",
    "xai", "grok", "mistral", "thinking machines", "mira murati",
    # Agent / dev infra brands your audience uses daily
    "nous", "hermes", "cua", "openclaw", "mcp", "agent skills",
    "cursor", "windsurf", "cline", "continue", "langchain",
    # SaaS brands that drove huge engagement when they open-sourced (Cal.com,
    # Perplexity Bumblebee, Karpathy CLAUDE.md). Adding because your top-10
    # shows the "established SaaS open-sourcing" angle is your best-performing
    # category, not just AI lab launches.
    "cal.com", "cal.diy", "perplexity", "bumblebee", "karpathy",
    "stripe", "vercel", "supabase", "notion", "linear",
]

# Phrases that mark "this is an open-source disruptor", which your audience loves.
# Order matters slightly for the first-match logging in the scorer.
OPEN_SOURCE_SIGNALS = [
    "open source", "open-sourced", "open sourced",
    "github.com/", "github.io/", "mit license", "apache 2",
    "free alternative", "self-host", "self host",
    "0 dollar", "no subscription", "killed the entire",
    # Verbs/phrases that signal "they gave away the product" — exact framing
    # of Keith's top performer (cal.diy): "raised $32M then open sourced"
    "raised", "forked their own", "released under mit",
    # Star-count callouts — these correlate with high engagement in Keith's data
    "github trending", "stars on github", "gone viral on github",
]

# Phrases marking a new launch (your audience over-indexes on novelty).
LAUNCH_SIGNALS = [
    "launching", "just launched", "we're launching", "announcing",
    "introducing", "today we", "now available", "ga today",
    "released", "shipping", "shipped today",
]


@dataclass
class ScoreResult:
    score: int
    reasoning: list[str]


def score_candidate(
    candidate: dict,
    *,
    existing_topics: Iterable[str] = (),
    now: datetime | None = None,
) -> ScoreResult:
    """Score one tweet candidate 0-100 against Keith's audience profile.

    candidate fields used: text, source_likes, source_retweets, source_views,
                          created_at (optional, ISO or twikit string), url
    existing_topics: lowercased text of Keith's recent posts so we can detect
                     novelty (skip topics he's already covered).
    """
    now = now or datetime.now(timezone.utc)
    text = (candidate.get("text") or "").lower()
    reasoning: list[str] = []
    score = 0

    # Feature 1: brand-name AI mention (your single strongest signal).
    # Match on word boundaries so "cua" doesn't match inside Spanish "cualquier".
    brands_hit = [b for b in AI_BRANDS if _word_match(b, text)]
    if brands_hit:
        # Cap at 30 so a tweet stuffed with 10 brand names doesn't dominate
        delta = min(30, 12 * len(brands_hit))
        score += delta
        reasoning.append(f"+{delta} brand-name AI: {', '.join(brands_hit[:3])}")

    # Feature 2: open-source signal
    os_hit = [s for s in OPEN_SOURCE_SIGNALS if _word_match(s, text)]
    if os_hit:
        delta = min(25, 15 * len(os_hit))
        score += delta
        reasoning.append(f"+{delta} open-source signal: {os_hit[0]!r}")

    # Feature 3: launch signal
    launch_hit = [l for l in LAUNCH_SIGNALS if _word_match(l, text)]
    if launch_hit:
        score += 10
        reasoning.append(f"+10 launch signal: {launch_hit[0]!r}")

    # Feature 4: engagement on source tweet (proxy for "this is going viral on X already")
    likes = int(candidate.get("source_likes") or 0)
    rts = int(candidate.get("source_retweets") or 0)
    if likes >= 5000 or rts >= 500:
        score += 15
        reasoning.append(f"+15 viral source ({likes:,}♥ {rts:,}RT)")
    elif likes >= 1000 or rts >= 100:
        score += 8
        reasoning.append(f"+8 strong engagement ({likes:,}♥ {rts:,}RT)")
    elif likes >= 200:
        score += 3
        reasoning.append(f"+3 modest engagement ({likes:,}♥ {rts:,}RT)")

    # Feature 5: freshness — older than 7 days is stale for launch content
    when = _parse_when(candidate.get("created_at"))
    if when is not None:
        age = now - when
        if age <= timedelta(hours=48):
            score += 10
            reasoning.append(f"+10 fresh (<48h, posted {age.days}d{age.seconds//3600}h ago)")
        elif age <= timedelta(days=7):
            score += 4
            reasoning.append(f"+4 recent ({age.days}d ago)")
        elif age > timedelta(days=21):
            score -= 10
            reasoning.append(f"-10 stale ({age.days}d ago)")

    # Feature 6: novelty — skip topics Keith already covered
    novelty_penalty = _novelty_penalty(text, existing_topics)
    if novelty_penalty > 0:
        score -= novelty_penalty
        reasoning.append(f"-{novelty_penalty} already covered (topic overlap)")

    # Feature 7: hostile content (replies, threads, link-only posts) — penalize
    if text.startswith("@") or text.startswith("rt @"):
        score -= 15
        reasoning.append("-15 looks like a reply/RT, not original content")
    if len(text) < 40:
        score -= 10
        reasoning.append(f"-10 very short ({len(text)} chars), low context")

    score = max(0, min(100, score))
    return ScoreResult(score=score, reasoning=reasoning)


def _parse_when(raw) -> datetime | None:
    """Accept ISO 8601 or twikit's 'Fri Nov 21 14:23:00 +0000 2025' format."""
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, str):
        # Try ISO first
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            pass
        # Twitter classic format
        try:
            return datetime.strptime(raw, "%a %b %d %H:%M:%S %z %Y")
        except ValueError:
            return None
    return None


def _novelty_penalty(candidate_text: str, existing_topics: Iterable[str]) -> int:
    """If the candidate shares a distinctive token with too many of Keith's recent
    posts, penalize. Distinctive tokens: 5+ char ASCII words and brand-like dots."""
    cand_tokens = _distinctive_tokens(candidate_text)
    if not cand_tokens:
        return 0
    hits = 0
    for topic in existing_topics:
        if cand_tokens & _distinctive_tokens(topic.lower()):
            hits += 1
    if hits >= 4:
        return 20  # heavy overlap with multiple past posts
    if hits >= 2:
        return 8
    return 0


_DOT_TOKEN_RE = re.compile(r"[a-z][a-z0-9]+\.[a-z][a-z0-9]+")
_WORD_RE = re.compile(r"[a-z]{5,}")


def _word_match(phrase: str, text: str) -> bool:
    """True if `phrase` appears in `text` at word boundaries (case-insensitive).
    Handles multi-word phrases ('google deepmind') and short tokens ('mcp')."""
    # Anchor with \b so 'cua' won't match inside 'cualquier'. For phrases with
    # special chars (like 'gpt-4'), we still need to escape.
    pattern = r"\b" + re.escape(phrase) + r"\b"
    return re.search(pattern, text) is not None


def _distinctive_tokens(text: str) -> set[str]:
    tokens = set(_DOT_TOKEN_RE.findall(text))
    tokens.update(_WORD_RE.findall(text))
    # Drop English filler that's not distinctive
    noise = {"about", "after", "again", "ahead", "along", "also", "another",
             "anything", "around", "because", "before", "being", "below",
             "between", "called", "company", "could", "every", "first",
             "going", "great", "happens", "hello", "important", "instead",
             "later", "looking", "might", "really", "right", "should",
             "since", "still", "their", "there", "these", "thing", "things",
             "those", "today", "weekend", "where", "which", "while", "would",
             "world", "years"}
    # Brand-name tokens repeat by design (Claude, OpenAI, etc. show up in many
    # posts). Don't count those as topic overlap — only count distinctive
    # product/concept names that signal "we already wrote about this thing".
    noise.update(AI_BRANDS)
    return {t for t in tokens if t not in noise}
