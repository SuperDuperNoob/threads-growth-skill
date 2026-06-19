"""Hard duplicate prevention for Threads candidates and drafts.

Autoposting needs stricter checks than "does this tweet id already exist?".
The same launch can show up through several X posts, a GitHub URL, a blog post,
or a rewritten draft. This module builds a small deterministic topic fingerprint
and blocks candidates that look like the same source, canonical URL, or idea as
anything already drafted, scheduled, handed off, or published.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from orbit.db import DB
from orbit.discovery import AI_BRANDS


COMMITTED_STATUSES = {
    "draft",
    "scheduled",
    "handed_off_to_postiz",
    "published",
}

_STOPWORDS = {
    "about", "after", "again", "agent", "agents", "already", "also",
    "another", "available", "because", "before", "being", "built", "called",
    "could", "every", "first", "github", "going", "hours", "launch",
    "launched", "model", "models", "open", "people", "released", "source",
    "still", "their", "there", "these", "thing", "things", "today", "using",
    "which", "while", "would", "不用", "免費", "開源", "剛剛", "可以",
}
_PRODUCT_STOPWORDS = _STOPWORDS | {
    "ai", "api", "app", "apps", "code", "dev", "free", "goal", "loop",
    "mcp", "ui", "url", "web",
    # Generic English common-nouns that get capitalized in marketing copy
    # ("Team and Enterprise plans", "Interactive pages") and were being
    # mistaken for product names — causing unrelated posts to collide.
    "available", "beta", "build", "built", "dashboard", "enterprise",
    "feature", "features", "interactive", "page", "pages", "plan", "plans",
    "private", "project", "release", "session", "sessions", "team", "teams",
    "update", "version", "walkthrough", "workflow", "workflows",
}
_TOKEN_RE = re.compile(r"[a-z][a-z0-9]+(?:\.[a-z][a-z0-9]+)?|[\u4e00-\u9fff]{2,}", re.I)
_URL_RE = re.compile(r"https?://[^\s)\]>\"']+")
_PRODUCT_RE = re.compile(r"\b[A-Z][A-Za-z0-9]*(?:\.[A-Za-z0-9]+)?\b")


@dataclass
class DuplicateDecision:
    is_duplicate: bool
    reason: str = ""
    matched_draft_id: int | None = None
    matched_status: str | None = None
    matched_content: str | None = None


def source_key(source: dict) -> str:
    """Stable source identity for exact duplicate blocking."""
    tweet_id = source.get("tweet_id")
    if tweet_id:
        return f"tweet:{tweet_id}"
    url = source.get("url")
    if url:
        return f"url:{canonicalize_url(url)}"
    text = " ".join((source.get("text") or "").lower().split())
    return f"text:{text[:180]}" if text else ""


def canonicalize_url(url: str | None) -> str:
    """Normalize URLs enough to catch same-source duplicates.

    Removes tracking query params and fragments but preserves meaningful paths.
    """
    if not url:
        return ""
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    keep_params = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower().startswith("utm_") or key.lower() in {
            "ref", "ref_src", "source", "s", "t", "tag", "fbclid", "gclid",
        }:
            continue
        keep_params.append((key, value))
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    return urlunparse((
        parsed.scheme.lower(),
        netloc,
        path,
        "",
        urlencode(keep_params),
        "",
    ))


def source_links(source: dict) -> list[str]:
    links = source.get("source_links") or []
    if isinstance(links, str):
        try:
            links = json.loads(links)
        except (TypeError, ValueError):
            links = [links]
    out: list[str] = []
    for link in links if isinstance(links, list) else []:
        canon = canonicalize_url(str(link))
        if canon:
            out.append(canon)
    source_url = canonicalize_url(source.get("url"))
    if source_url:
        out.append(source_url)
    text = source.get("text") or ""
    for raw in _URL_RE.findall(text):
        canon = canonicalize_url(raw)
        if canon:
            out.append(canon)
    seen: set[str] = set()
    deduped: list[str] = []
    for link in out:
        if link in seen:
            continue
        seen.add(link)
        deduped.append(link)
    return deduped


def canonical_url_for_source(source: dict) -> str:
    """Prefer non-X project/blog links over the X post URL."""
    links = source_links(source)
    non_x = [
        u for u in links
        if not any(host in urlparse(u).netloc for host in ("x.com", "twitter.com"))
    ]
    return non_x[0] if non_x else (links[0] if links else "")


def entities_for_text(text: str) -> list[str]:
    lower = (text or "").lower()
    entities = [brand for brand in AI_BRANDS if _contains_phrase(lower, brand)]
    # Capture CamelCase / product-ish ASCII terms from original casing.
    product_terms = re.findall(r"\b[A-Z][A-Za-z0-9]*(?:\.[A-Za-z0-9]+)?\b", text or "")
    for term in product_terms:
        lowered = term.lower()
        if len(lowered) < 3 or lowered in _STOPWORDS:
            continue
        if lowered not in entities:
            entities.append(lowered)
    return entities[:12]


def topic_fingerprint(text: str, source: dict | None = None) -> str:
    """A deterministic "same idea" key from brand/product/distinctive tokens."""
    source = source or {}
    links = source.get("source_links") or []
    if isinstance(links, str):
        try:
            links = json.loads(links)
        except (TypeError, ValueError):
            links = [links]
    if not isinstance(links, list):
        links = []
    combined = " ".join([
        text or "",
        source.get("text") or "",
        source.get("url") or "",
        " ".join(str(x) for x in links if x),
    ])
    entities = entities_for_text(combined)
    tokens = [
        t.lower()
        for t in _TOKEN_RE.findall(combined.lower())
        if len(t) >= 4 and t.lower() not in _STOPWORDS
    ]
    # Entity tokens first because brand/product identity matters more than prose.
    ordered: list[str] = []
    for token in [*entities, *tokens]:
        token = token.lower()
        if token not in ordered:
            ordered.append(token)
    return ":".join(ordered[:8])


def check_duplicate(
    db: DB,
    *,
    content: str,
    source: dict | None = None,
    platform: str = "threads",
    lexical_threshold: float = 0.58,
) -> DuplicateDecision:
    """Return a blocking duplicate decision against committed local content."""
    source = source or {}
    skey = source_key(source)
    canon = canonical_url_for_source(source)
    fingerprint = topic_fingerprint(content, source)
    tokens = _distinctive_tokens(" ".join([content or "", source.get("text") or ""]))

    for row in _committed_rows(db, platform):
        row_content = row.get("content") or ""
        row_source = {
            "url": row.get("source_url"),
            "source_links": row.get("source_links"),
        }
        row_skey = row.get("source_key") or source_key(row_source)
        row_canon = row.get("canonical_url") or canonical_url_for_source(row_source)
        row_fp = row.get("topic_fingerprint") or topic_fingerprint(row_content, row_source)

        if skey and row_skey and skey == row_skey:
            return _decision("same source", row)
        if canon and row_canon and canon == row_canon:
            return _decision("same canonical URL", row)
        fp_overlap = _fingerprint_overlap(fingerprint, row_fp) if (fingerprint and row_fp) else 0.0
        # Sharing a brand is NOT enough on its own — the same tool gets covered
        # many times for different launches (e.g. Claude Code Loop vs. Artifacts).
        # We only block on a shared *distinctive* product/coined name. Generic
        # marketing words (enterprise, interactive, team, session, …) are filtered
        # out by _product_tokens so they no longer cause unrelated collisions.
        shared_products = _distinctive_products(
            " ".join([content or "", source.get("text") or ""])
        ) & _distinctive_products(row_content)
        if shared_products:
            return _decision(f"same product/entity: {', '.join(sorted(shared_products)[:3])}", row)
        if fp_overlap >= 0.72:
            return _decision("same topic fingerprint", row)

        row_tokens = _distinctive_tokens(row_content)
        if tokens and row_tokens:
            sim = _jaccard(tokens, row_tokens)
            if sim >= lexical_threshold:
                return _decision(f"high lexical overlap ({sim:.2f})", row)

    return DuplicateDecision(False)


def filter_duplicate_sources(db: DB, sources: list[dict], *, platform: str = "threads") -> tuple[list[dict], list[tuple[dict, DuplicateDecision]]]:
    """Drop sources that already look covered. Returns (kept, dropped)."""
    kept: list[dict] = []
    dropped: list[tuple[dict, DuplicateDecision]] = []
    for source in sources:
        decision = check_duplicate(
            db,
            content=source.get("text") or "",
            source=source,
            platform=platform,
        )
        if decision.is_duplicate:
            dropped.append((source, decision))
        else:
            kept.append(source)
    return kept, dropped


def record_content(
    db: DB,
    *,
    draft_id: int,
    content: str,
    source: dict | None = None,
    platform: str = "threads",
    status: str = "draft",
) -> None:
    """Persist a ledger row for future duplicate checks."""
    source = source or {}
    now = datetime.now(timezone.utc).isoformat()
    skey = source_key(source)
    row = {
        "platform": platform,
        "draft_id": draft_id,
        "source_key": skey or None,
        "canonical_url": canonical_url_for_source(source) or None,
        "topic_fingerprint": topic_fingerprint(content, source) or None,
        "entities": json.dumps(entities_for_text(" ".join([content, source.get("text") or ""]))),
        "content": content,
        "status": status,
        "created_at": now,
    }
    existing = None
    if skey:
        existing = db.conn.execute(
            "SELECT id FROM content_ledger WHERE platform = ? AND source_key = ?",
            [platform, skey],
        ).fetchone()
    if existing:
        db.conn["content_ledger"].update(existing[0], row)
    else:
        db.conn["content_ledger"].insert(row)


def _committed_rows(db: DB, platform: str) -> list[dict]:
    rows: list[dict] = []
    try:
        rows.extend(dict(r) for r in db.conn.query(
            """
            SELECT d.id AS draft_id, d.status, d.content, d.source_url, d.source_links,
                   NULL AS source_key, NULL AS canonical_url, NULL AS topic_fingerprint
            FROM drafts d
            LEFT JOIN posts p
              ON p.draft_id = d.id AND p.platform = ?
            WHERE d.platform = ?
              AND d.content IS NOT NULL AND d.content != ''
              AND (
                d.status IN ('draft', 'scheduled', 'handed_off_to_postiz', 'published')
                OR (p.published_at IS NOT NULL AND p.published_at != '')
              )
            """,
            [platform, platform],
        ))
    except Exception:
        pass
    try:
        rows.extend(dict(r) for r in db.conn.query(
            """
            SELECT draft_id, status, content, NULL AS source_url, NULL AS source_links,
                   source_key, canonical_url, topic_fingerprint
            FROM content_ledger
            WHERE platform = ?
              AND status IN ('draft', 'scheduled', 'handed_off_to_postiz', 'published')
              AND content IS NOT NULL AND content != ''
            """,
            [platform],
        ))
    except Exception:
        pass
    return rows


def _decision(reason: str, row: dict) -> DuplicateDecision:
    return DuplicateDecision(
        True,
        reason=reason,
        matched_draft_id=row.get("draft_id"),
        matched_status=row.get("status"),
        matched_content=(row.get("content") or "")[:160],
    )


def _fingerprint_overlap(a: str, b: str) -> float:
    left = {x for x in a.split(":") if x}
    right = {x for x in b.split(":") if x}
    return _jaccard(left, right)


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _distinctive_tokens(text: str) -> set[str]:
    return {
        t.lower()
        for t in _TOKEN_RE.findall(text or "")
        if len(t) >= 4 and t.lower() not in _STOPWORDS
    }


def _product_tokens(text: str) -> set[str]:
    brands = {b.lower() for b in AI_BRANDS}
    out: set[str] = set()
    for term in _PRODUCT_RE.findall(text or ""):
        lowered = term.lower()
        if len(lowered) < 5:
            continue
        if lowered in brands or lowered in _PRODUCT_STOPWORDS:
            continue
        out.add(lowered)
    return out


def _distinctive_products(text: str) -> set[str]:
    """Product tokens that identify a *specific* tool, used for hard blocking.

    A known AI brand (anthropic, openai, …) is too broad on its own — every
    Claude Code post mentions "claude". We block only on the narrower coined
    product/feature names (Hivemind, Artifacts, optimizerDuck) so the same brand
    can be covered repeatedly for different launches, while the same launch
    described twice still collides on its distinctive name.
    """
    brands = {b.lower() for b in AI_BRANDS}
    return {t for t in _product_tokens(text) if t not in brands}


def _contains_phrase(text: str, phrase: str) -> bool:
    return re.search(r"\b" + re.escape(phrase.lower()) + r"\b", text) is not None
