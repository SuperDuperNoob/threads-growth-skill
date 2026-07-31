from __future__ import annotations
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from orbit.analysis import build_pattern_prompt, extract_top_patterns
from orbit.config import Config
from orbit.db import DB
from orbit.duplicates import check_duplicate, filter_duplicate_sources, record_content
from orbit.embeddings import embed_texts, filter_duplicates, rank_bookmarks, unpack_embedding
from orbit.platforms.threads import ThreadsClient
from orbit.platforms.twitter import BookmarkCache, TwitterClient

app = typer.Typer(help="Generate Threads drafts from your X bookmarks")
console = Console()

_CACHE_PATH = Path.home() / ".orbit" / "bookmarks_cache.json"


@app.callback(invoke_without_command=True)
def draft(
    force_refresh: bool = typer.Option(False, "--refresh", "-r", help="Force re-fetch bookmarks"),
    json_out: bool = typer.Option(
        False, "--json",
        help="Non-interactive: generate, score, save drafts, print JSON to stdout. "
             "No prompts, no scheduling. For agent/headless use (Hermes).",
    ),
) -> None:
    cfg = Config()
    db = DB()

    # In JSON mode all human-facing status goes to stderr so stdout carries
    # only the final JSON payload that Hermes parses.
    status = Console(stderr=True) if json_out else console

    cookies_path = cfg.get("twitter.cookies_path")
    if not cookies_path:
        status.print("\n[red]✗ Twitter not configured.[/red] Run: [cyan]orbit setup --platform twitter[/cyan]\n")
        raise typer.Exit(1)

    api_key = os.environ.get("ANTHROPIC_API_KEY") or cfg.get("anthropic.api_key")
    if not api_key:
        status.print("\n[red]✗ ANTHROPIC_API_KEY not set.[/red]")
        status.print("  Set it with: [cyan]export ANTHROPIC_API_KEY=sk-ant-...[/cyan]")
        status.print("  Or run: [cyan]orbit setup --platform anthropic[/cyan]\n")
        raise typer.Exit(1)

    cache = BookmarkCache(_CACHE_PATH)
    bookmarks = None if force_refresh else cache.load()

    if bookmarks is None:
        status.print("\n[dim]Fetching X bookmarks...[/dim]")
        try:
            client = TwitterClient(cookies_path=cookies_path)
            bookmarks = client.get_bookmarks(limit=50)
            cache.save(bookmarks)
            status.print(f"  [green]✓[/green] Fetched {len(bookmarks)} bookmarks\n")
        except FileNotFoundError:
            status.print("\n[red]✗ Cookie file not found.[/red] Re-run: [cyan]orbit setup --platform twitter[/cyan]\n")
            raise typer.Exit(1)
        except Exception as e:
            msg = str(e)
            status.print(f"\n[red]✗ Failed to fetch bookmarks: {msg}[/red]")
            if "anti-bot" in msg or "KEY_BYTE" in msg:
                status.print("  [dim]This is usually transient. Try again in a minute.[/dim]\n")
            elif "401" in msg or "403" in msg or "auth" in msg.lower():
                status.print("  Your session may have expired. Re-run: [cyan]orbit setup --platform twitter[/cyan]\n")
            else:
                status.print("  [dim]Re-run with[/dim] [cyan]orbit draft -r[/cyan] [dim]to retry, or[/dim] [cyan]orbit setup --platform twitter[/cyan] [dim]to refresh cookies.[/dim]\n")
            raise typer.Exit(1)
    else:
        status.print(f"\n[dim]Using cached bookmarks ({len(bookmarks)} items)[/dim]\n")

    if not bookmarks:
        status.print("[yellow]No bookmarks found.[/yellow] Make sure you have bookmarks on X.\n")
        raise typer.Exit(1)

    if json_out:
        # Bulletproof stdout discipline: redirect ALL stdout (Rich console,
        # plain print, any helper) to stderr for the whole generation, so the
        # only thing on real stdout is the JSON payload, written via the saved
        # handle below. Individual call-site redirection is whack-a-mole; this
        # covers helpers (_filter_hard_duplicate_sources etc.) we can't thread
        # `status` into.
        import sys
        from contextlib import redirect_stdout
        real_stdout = sys.stdout
        with redirect_stdout(sys.stderr):
            _run_draft_generation(bookmarks, json_out=json_out, json_stream=real_stdout)
    else:
        _run_draft_generation(bookmarks, json_out=json_out)


def _judge_sources(ai, sources, recent_topics, top_patterns, cfg_quality, status):
    """LLM re-rank of shortlisted sources by novelty/width/fit. Fail-open to input order."""
    if not cfg_quality["source_judge"] or not sources:
        return sources
    from orbit.source_judge import (
        build_source_judge_prompt,
        parse_source_judgment,
        rank_judged,
    )
    try:
        prompt = build_source_judge_prompt(sources, recent_topics, top_patterns)
        msg = ai.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        judged = parse_source_judgment(msg.content[0].text)
    except Exception as e:  # noqa: BLE001 — fail-open, log visibly
        status.print(f"[yellow]⚠ Source judge failed ({e}); using embedding order.[/yellow]")
        return sources
    if not judged:
        status.print("[yellow]⚠ Source judge returned nothing; using embedding order.[/yellow]")
        return sources
    ranked = rank_judged(judged, novelty_weight=cfg_quality["novelty_weight"])
    reordered = [sources[j["index"]] for j in ranked if 0 <= j["index"] < len(sources)]
    return reordered or sources


def _critique_and_refine(ai, draft_text, top_patterns, cfg_quality, status):
    """Grade a draft; refine once if below threshold; return the better text.

    Fail-open: any error returns the original draft unchanged.
    """
    if not cfg_quality["critic"]:
        return draft_text
    from orbit.critic import (
        build_critic_prompt,
        parse_critique,
        build_refine_prompt,
        pick_better,
    )

    def _grade(text):
        try:
            msg = ai.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=512,
                messages=[{"role": "user", "content": build_critic_prompt(text, top_patterns)}],
            )
            return parse_critique(msg.content[0].text)
        except Exception as e:  # noqa: BLE001
            status.print(f"[yellow]⚠ Critic failed ({e}); keeping draft as-is.[/yellow]")
            return None

    original_crit = _grade(draft_text)
    if original_crit is None:
        return draft_text
    if original_crit["total"] >= cfg_quality["refine_threshold"]:
        return draft_text
    try:
        rmsg = ai.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": build_refine_prompt(draft_text, original_crit, top_patterns)}],
        )
        refined_text = rmsg.content[0].text.strip()
    except Exception as e:  # noqa: BLE001
        status.print(f"[yellow]⚠ Refine failed ({e}); keeping original.[/yellow]")
        return draft_text
    refined_crit = _grade(refined_text)
    better, _ = pick_better(
        (draft_text, original_crit),
        (refined_text, refined_crit) if refined_crit else None,
    )
    return better


def _run_draft_generation(sources: list[dict], *, json_out: bool = False, json_stream=None) -> None:
    """Generate, display, save, and offer to publish Threads drafts.

    Shared entry point used by both `orbit draft` (bookmarks) and
    `orbit discover draft` (curated candidates). `sources` is a list of dicts
    with at least 'text', 'author', 'url' (matches BookmarkCache shape).

    When json_out=True, runs non-interactively: generates and scores drafts,
    saves them, prints a JSON payload to stdout (status to stderr), and returns
    WITHOUT the interactive picker, LinkedIn prompt, or post-save action. This
    is the path the Hermes agent drives headlessly.
    """
    cfg = Config()
    db = DB()
    # All human-facing chatter goes to stderr in JSON mode; stdout is reserved
    # for the single JSON payload at the end.
    status = Console(stderr=True) if json_out else console
    api_key = os.environ.get("ANTHROPIC_API_KEY") or cfg.get("anthropic.api_key")
    if not api_key:
        status.print("\n[red]✗ ANTHROPIC_API_KEY not set.[/red]")
        status.print("  Set it with: [cyan]export ANTHROPIC_API_KEY=sk-ant-...[/cyan]")
        status.print("  Or run: [cyan]orbit setup --platform anthropic[/cyan]\n")
        raise typer.Exit(1)

    # Auto-sync recent Threads posts if data is stale (>1 hour). Without this,
    # dedup compares against a snapshot taken at last manual sync — meaning
    # anything you posted today won't be caught as a duplicate. Skipped silently
    # if the sync fails (offline, auth expired, etc) so drafting still works.
    _maybe_auto_sync_threads(cfg, db)

    rows = db.conn.execute("""
        SELECT d.content, m.views, m.likes, p.embedding
        FROM posts p
        JOIN drafts d ON d.id = p.draft_id
        JOIN metrics m ON m.post_id = p.id
        WHERE p.platform = 'threads'
        ORDER BY m.views DESC
        LIMIT 10
    """).fetchall()

    if not rows:
        status.print("[yellow]No Threads data yet.[/yellow] Run [cyan]orbit sync --platform threads[/cyan] first.\n")
        raise typer.Exit(1)

    top_posts = [{"content": r[0], "views": r[1], "likes": r[2]} for r in rows]
    top_patterns = extract_top_patterns(top_posts, top_n=5)

    # Embed bookmarks once — used by both dedup-against-published and rank-by-winners.
    # Falls back to empty vectors when OpenAI is unavailable so the rest of the flow
    # still works (just without similarity-based filtering or ranking).
    bookmark_vectors = _safe_embed([s.get("text", "") for s in sources])

    # Drop bookmarks the user explicitly dismissed in a previous session.
    # Embedding-similarity dedup is a guess; "marked done" is ground truth.
    sources, bookmark_vectors = _filter_dismissed_sources(db, sources, bookmark_vectors)

    sources, bookmark_vectors = _filter_hard_duplicate_sources(db, sources, bookmark_vectors)
    if not sources:
        status.print("[yellow]All sources look like topics you've already drafted, scheduled, or posted.[/yellow]")
        status.print("  [dim]Try pulling a wider discovery batch or new X bookmarks.[/dim]\n")
        _exit_empty(json_out, json_stream, db)

    # Drop bookmarks that look like news items we already posted about.
    # Without this, the source pool keeps offering the same Cal.com / Hermes / etc.
    # stories that the user already turned into published Threads posts.
    sources, bookmark_vectors = _dedupe_against_published(db, sources, bookmark_vectors)
    if not sources:
        status.print("[yellow]All bookmarks look like news you've already posted or dismissed.[/yellow]")
        status.print("  [dim]Try bookmarking some fresh content on X, then run `orbit draft -r`.[/dim]\n")
        _exit_empty(json_out, json_stream, db)

    # Rank bookmarks by similarity to the top-10 winners. Falls back to original
    # order when embeddings aren't available yet (fresh DB, or OpenAI down).
    # top_k=20 to give the regenerate flow + 6-draft display enough headroom.
    winner_vectors = [unpack_embedding(r[3]) for r in rows]
    selected_sources = _rank_sources_by_similarity(
        sources, winner_vectors, top_k=20, bookmark_vectors=bookmark_vectors,
    )
    selected_sources = _require_media_sources(selected_sources, status=status)
    if not selected_sources:
        _exit_empty(json_out, json_stream, db)

    # Last 5 posted topics — feeds the prompt's TOPIC FATIGUE GUARD so the LLM
    # avoids covering the same brand/cluster as a recent post (algorithm
    # suppresses consecutive-topic clustering per SKILL.md S5/S14). Computed
    # here (moved up from just below the media filter) so the source judge can
    # penalize repeats before the sources are used to build the prompt.
    recent_topics = _recent_threads_topics(db, limit=5)
    recent_performance = _recent_threads_performance(db, limit=7)

    # Single Anthropic client, reused by the source judge AND the generation
    # call below (do not construct twice).
    ai = anthropic.Anthropic(api_key=api_key)

    # Stage 1: LLM re-rank of the shortlisted sources by novelty/width/fit.
    # Fail-open — any error keeps the embedding-similarity order untouched.
    from orbit.source_judge import quality_config
    cfg_quality = quality_config(cfg._data)
    selected_sources = _judge_sources(
        ai, selected_sources, recent_topics, top_patterns, cfg_quality, status,
    )

    draft_count = min(6, len(selected_sources))
    status.print(f"[dim]Generating {draft_count} drafts with Claude...[/dim]\n")
    prompt = build_pattern_prompt(
        top_patterns,
        selected_sources,
        recent_topics=recent_topics,
        recent_performance=recent_performance,
        count=draft_count,
    )

    message = ai.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,  # 6 drafts need more output budget than 3
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text

    drafts = _parse_drafts(raw)

    if not drafts:
        status.print("[red]✗ Could not parse drafts from Claude response.[/red]")
        status.print(raw)
        raise typer.Exit(1)

    # Stage 2: per-draft LLM critic + single refine. Fail-open — each draft is
    # graded, refined once if below threshold, and only replaced when the refined
    # version strictly beats the original. Runs before source-matching so both the
    # json and interactive paths use the (possibly refined) text downstream.
    drafts = [
        _critique_and_refine(ai, d, top_patterns, cfg_quality, status)
        for d in drafts
    ]

    # Track which bookmarks the initial drafts came from. Used by both:
    # - regenerate (swap a draft for one built from a fresh unused bookmark)
    # - dismiss (mark "i don't want to see this bookmark again" to disk)
    # Falls back to positional pairing when token-overlap matching can't find
    # a strong source.
    draft_sources = [
        _best_source_match(d, selected_sources) or (selected_sources[i] if i < len(selected_sources) else {})
        for i, d in enumerate(drafts)
    ]
    used_source_keys = {_source_key(s) for s in draft_sources if s}

    # Headless path: save every generated draft, score them, emit JSON, return.
    # No picker, no LinkedIn prompt, no post-save action — Hermes decides which
    # saved draft_ids to schedule via `orbit drafts schedule <id>`.
    if json_out:
        import json as _json
        now = datetime.now(timezone.utc).isoformat()
        saved_ids: list[int] = []
        saved_texts: list[str] = []
        saved_sources: list[dict] = []
        for i, draft_text in enumerate(drafts):
            matched_source = draft_sources[i] if i < len(draft_sources) else (selected_sources[0] if selected_sources else {})
            # Skip hard duplicates so Hermes never even sees an already-covered topic.
            duplicate = check_duplicate(db, content=draft_text, source=matched_source)
            if duplicate.is_duplicate:
                status.print(f"[yellow]⚠ Skipped (duplicate: {duplicate.reason})[/yellow]")
                continue
            idea_id = db.conn["ideas"].insert({
                "title": draft_text[:80], "source": "draft",
                "status": "draft", "created_at": now,
            }).last_pk
            source_links = matched_source.get("source_links") or []
            did = db.conn["drafts"].insert({
                "idea_id": idea_id, "platform": "threads", "content": draft_text,
                "status": "draft", "source_url": matched_source.get("url"),
                "media_url": matched_source.get("media_url"),
                "media_type": matched_source.get("media_type"),
                "source_links": _json.dumps(source_links) if source_links else None,
                "created_at": now,
            }).last_pk
            record_content(db, draft_id=did, content=draft_text, source=matched_source, status="draft")
            saved_ids.append(did)
            saved_texts.append(draft_text)
            saved_sources.append(matched_source)

        payload = build_draft_json_payload(
            saved_texts, saved_sources, saved_ids,
            recent_topics=recent_topics, generated_at=now,
        )
        # Write JSON to the real stdout handle (callers redirect stdout→stderr
        # during generation, so this is the only thing on actual stdout).
        import sys as _sys
        out = json_stream if json_stream is not None else _sys.stdout
        print(_json.dumps(payload, ensure_ascii=False, indent=2), file=out)
        return

    picks = _select_loop(
        drafts, ai, prompt,
        source_pool=selected_sources,
        used_source_keys=used_source_keys,
        top_patterns=top_patterns,
        recent_topics=recent_topics,
        draft_sources=draft_sources,
        db=db,
    )
    if not picks:
        console.print("\n[dim]Discarded. Run again for fresh drafts.[/dim]\n")
        return

    saved_ids: list[int] = []
    now = datetime.now(timezone.utc).isoformat()
    import json as _json
    matched_sources_by_draft: dict[int, dict] = {}
    for idx in picks:
        matched_source = _best_source_match(drafts[idx], selected_sources) or (selected_sources[0] if selected_sources else {})
        duplicate = check_duplicate(db, content=drafts[idx], source=matched_source)
        if duplicate.is_duplicate:
            console.print(
                f"\n[yellow]⚠ Skipped draft {idx + 1}: duplicate blocked "
                f"({duplicate.reason}"
                f"{f', draft {duplicate.matched_draft_id}' if duplicate.matched_draft_id else ''}).[/yellow]"
            )
            continue
        idea_id = db.conn["ideas"].insert({
            "title": drafts[idx][:80],
            "source": "draft",
            "status": "draft",
            "created_at": now,
        }).last_pk
        # Find the source bookmark each draft was inspired by, by token overlap.
        # Falls back to the first source if no strong match (better than nothing).
        matched_sources_by_draft[idx] = matched_source
        source_links = matched_source.get("source_links") or []
        draft_id = db.conn["drafts"].insert({
            "idea_id": idea_id,
            "platform": "threads",
            "content": drafts[idx],
            "status": "draft",
            "source_url": matched_source.get("url"),
            "media_url": matched_source.get("media_url"),
            "media_type": matched_source.get("media_type"),
            "source_links": _json.dumps(source_links) if source_links else None,
            "created_at": now,
        }).last_pk
        record_content(
            db,
            draft_id=draft_id,
            content=drafts[idx],
            source=matched_source,
            status="draft",
        )
        saved_ids.append(draft_id)

    if not saved_ids:
        console.print("\n[red]No drafts saved; every selected draft matched an existing topic.[/red]\n")
        return

    saved_label = ", ".join(str(i + 1) for i in picks)
    console.print(f"\n[green]✓ Saved Threads draft(s) {saved_label}.[/green]\n")

    # Offer to also generate a LinkedIn variant from the same sources. LinkedIn
    # has different norms (longer, English-heavy, personal-stake) so we use a
    # separate prompt — never just cross-post the Threads copy.
    linkedin_ids = _maybe_generate_linkedin(
        db, ai, [matched_sources_by_draft[i] for i in picks if i in matched_sources_by_draft], now,
    )
    saved_ids.extend(linkedin_ids)

    _post_save_action(db, saved_ids, [drafts[i] for i in picks], cfg)


def _recent_threads_topics(db: DB, limit: int = 5) -> list[str]:
    """Return the first 80 chars of the `limit` most-recently published Threads posts.

    Feeds the prompt's TOPIC FATIGUE GUARD. We use draft.content (the post body)
    truncated to a short label rather than computing a "topic" — the LLM is
    perfectly capable of judging brand/cluster overlap from the raw opener.
    Ordered by published_at DESC; falls back to empty list on any error.
    """
    try:
        rows = db.conn.execute("""
            SELECT substr(d.content, 1, 80)
            FROM posts p
            JOIN drafts d ON d.id = p.draft_id
            WHERE p.platform = 'threads'
              AND p.published_at IS NOT NULL AND p.published_at != ''
            ORDER BY p.published_at DESC
            LIMIT ?
        """, [limit]).fetchall()
        return [(r[0] or "").strip().replace("\n", " ") for r in rows if r[0]]
    except Exception:
        return []


def _recent_threads_performance(db: DB, limit: int = 7) -> dict:
    """Summarize recent Threads like-rate health for the prompt.

    Uses the latest published Threads posts in local metrics. Empty dict on any
    error so draft generation can continue even when metrics are sparse.
    """
    try:
        rows = db.conn.execute("""
            SELECT substr(d.content, 1, 80), m.views, m.likes
            FROM posts p
            JOIN drafts d ON d.id = p.draft_id
            JOIN metrics m ON m.post_id = p.id
            WHERE p.platform = 'threads'
              AND p.published_at IS NOT NULL AND p.published_at != ''
              AND m.views IS NOT NULL
            ORDER BY p.published_at DESC, m.pulled_at DESC
            LIMIT ?
        """, [limit]).fetchall()
    except Exception:
        return {}

    like_rates: list[float] = []
    examples: list[dict] = []
    baseline = 1.17
    for opening, views, likes in rows:
        views = views or 0
        likes = likes or 0
        if views <= 0:
            continue
        like_rate = round(likes / views * 100, 2)
        like_rates.append(like_rate)
        if like_rate < baseline:
            examples.append({
                "opening": (opening or "").strip().replace("\n", " "),
                "like_rate": like_rate,
            })

    if not like_rates:
        return {}

    sorted_rates = sorted(like_rates)
    mid = len(sorted_rates) // 2
    if len(sorted_rates) % 2:
        median = sorted_rates[mid]
    else:
        median = round((sorted_rates[mid - 1] + sorted_rates[mid]) / 2, 2)
    below = sum(1 for rate in like_rates if rate < baseline)
    return {
        "sample_size": len(like_rates),
        "baseline_like_rate": baseline,
        "median_like_rate": median,
        "below_baseline_count": below,
        "weak_recent_performance": below >= max(2, len(like_rates) // 2 + 1),
        "examples": examples[:3],
    }


def _rank_sources_by_similarity(
    sources: list[dict],
    winner_vectors: list[list[float]],
    top_k: int = 10,
    bookmark_vectors: list[list[float]] | None = None,
) -> list[dict]:
    """Score each source against the top Threads winners and return the best `top_k`.

    When `bookmark_vectors` is provided, skip the OpenAI call and reuse them
    (the dedup step embeds the same texts, no need to pay twice). Falls back
    to fetching when None.

    Falls back to the original first-N slice when:
    - No winner has an embedding yet (fresh DB before first embedding sync)
    - The OpenAI call fails (network, key, rate limit) — we don't want a flaky
      embedding service to block draft generation
    """
    if not sources:
        return []
    if not any(winner_vectors):
        return sources[:top_k]

    if bookmark_vectors is None:
        try:
            bookmark_vectors = embed_texts([s.get("text", "") for s in sources])
        except Exception as e:
            console.print(f"  [yellow]⚠ ranking skipped ({e}); using newest bookmarks[/yellow]")
            return sources[:top_k]

    if not any(bookmark_vectors):
        return sources[:top_k]

    ranked = rank_bookmarks(sources, bookmark_vectors, winner_vectors, top_k=top_k)
    if ranked:
        top_score = ranked[0].get("_score", 0.0)
        bottom_score = ranked[-1].get("_score", 0.0)
        console.print(
            f"  [dim]Ranked {len(sources)} bookmarks by similarity to top winners "
            f"(scores {top_score:.2f}–{bottom_score:.2f})[/dim]"
        )
    return ranked


def _require_media_sources(sources: list[dict], *, status=None) -> list[dict]:
    """Return only sources that carry image/video media for Threads drafts.

    Threads posts should be media-backed whenever Orbit schedules them. Returns
    the media-backed subset (possibly empty — the caller decides how to handle
    "no media", so the JSON path can emit an empty payload instead of crashing).
    Status notes go to the passed-in console (stderr in --json mode).
    """
    out = status or console
    media_sources = [s for s in sources if s.get("media_url")]
    if not media_sources:
        out.print(
            "[yellow]No image/video-backed sources available in this batch.[/yellow]"
        )
        out.print(
            "  [dim]Bookmark posts with screenshots/videos, then run[/dim] "
            "[cyan]orbit draft -r[/cyan][dim].[/dim]\n"
        )
    elif len(media_sources) < len(sources):
        out.print(
            f"  [dim]Using {len(media_sources)} media-backed source(s); "
            f"skipped {len(sources) - len(media_sources)} text-only source(s).[/dim]"
        )
    return media_sources


def _safe_embed(texts: list[str]) -> list[list[float]]:
    """Embed `texts` via OpenAI, returning empty vectors on any failure.

    Used by both the dedup and rank flows. Returning empty vectors (rather than
    raising) lets the calling flow degrade gracefully — no embeddings means no
    dedup and no ranking, but draft generation still works.
    """
    if not texts:
        return []
    try:
        return embed_texts(texts)
    except Exception as e:
        console.print(f"  [yellow]⚠ embedding failed ({e}); skipping dedup + rank[/yellow]")
        return [[] for _ in texts]


def _dedupe_against_published(
    db: DB,
    sources: list[dict],
    bookmark_vectors: list[list[float]],
    *,
    recent_limit: int = 30,
) -> tuple[list[dict], list[list[float]]]:
    """Drop bookmarks that look like news items already turned into published posts.

    Pulls the last `recent_limit` published Threads posts, embeds them, then
    runs filter_duplicates() against the bookmark pool. Reports any dropped
    bookmarks so the user knows why their list shrank.

    No-op when there are no published posts (fresh DB) or when bookmark embedding
    failed upstream (empty vectors).
    """
    if not bookmark_vectors or not any(bookmark_vectors):
        return sources, bookmark_vectors

    published_texts = _recent_published_threads_content(db, limit=recent_limit)
    if not published_texts:
        return sources, bookmark_vectors

    published_vectors = _safe_embed(published_texts)
    if not any(published_vectors):
        return sources, bookmark_vectors

    kept, kept_vectors, dropped = filter_duplicates(
        sources, bookmark_vectors, published_vectors
    )
    if dropped:
        console.print(
            f"  [dim]Filtered {len(dropped)} bookmark(s) matching already-published posts "
            f"(threshold {0.80}).[/dim]"
        )
    return kept, kept_vectors


_AUTO_SYNC_STALE_SECONDS = 3600  # 1 hour


def _ensure_dismissed_table(db: DB) -> None:
    """Create the dismissed_sources table if it doesn't exist.

    Lazily called from the dismiss + filter paths so the schema is created
    on first use, no migration step required. Keyed by source_key so the
    same bookmark URL is only stored once even if dismissed multiple times.
    """
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS dismissed_sources (
            source_key TEXT PRIMARY KEY,
            url TEXT,
            text_preview TEXT,
            dismissed_at TEXT NOT NULL
        )
    """)


def _add_dismissed_source(db: DB, source: dict) -> bool:
    """Insert a source into dismissed_sources. Returns True if newly added,
    False if it was already there (no-op).
    """
    _ensure_dismissed_table(db)
    key = _source_key(source)
    if not key:
        return False
    existing = db.conn.execute(
        "SELECT 1 FROM dismissed_sources WHERE source_key = ?", [key]
    ).fetchone()
    if existing:
        return False
    db.conn.execute(
        "INSERT INTO dismissed_sources (source_key, url, text_preview, dismissed_at) "
        "VALUES (?, ?, ?, ?)",
        [
            key,
            source.get("url"),
            (source.get("text") or "")[:120],
            datetime.now(timezone.utc).isoformat(),
        ],
    )
    return True


def _dismissed_source_keys(db: DB) -> set[str]:
    """Return all dismissed source keys. Empty set on first-ever call (no table)."""
    try:
        _ensure_dismissed_table(db)
        rows = db.conn.execute("SELECT source_key FROM dismissed_sources").fetchall()
        return {r[0] for r in rows if r[0]}
    except Exception:
        return set()


def _filter_dismissed_sources(
    db: DB,
    sources: list[dict],
    bookmark_vectors: list[list[float]],
) -> tuple[list[dict], list[list[float]]]:
    """Drop bookmarks the user previously marked as done. Returns the kept
    bookmarks + their vectors (preserving alignment).

    Reports the count so the user knows the filter is doing something.
    """
    dismissed = _dismissed_source_keys(db)
    if not dismissed:
        return sources, bookmark_vectors

    kept_sources: list[dict] = []
    kept_vectors: list[list[float]] = []
    dropped = 0
    for src, vec in zip(sources, bookmark_vectors):
        if _source_key(src) in dismissed:
            dropped += 1
            continue
        kept_sources.append(src)
        kept_vectors.append(vec)

    if dropped:
        console.print(
            f"  [dim]Skipped {dropped} bookmark(s) you marked as done.[/dim]"
        )
    return kept_sources, kept_vectors


def _filter_hard_duplicate_sources(
    db: DB,
    sources: list[dict],
    bookmark_vectors: list[list[float]],
) -> tuple[list[dict], list[list[float]]]:
    """Drop candidates that match already drafted/scheduled/published topics."""
    kept_sources, dropped = filter_duplicate_sources(db, sources)
    if not dropped:
        return sources, bookmark_vectors

    kept_keys = {_source_key(s) for s in kept_sources}
    kept_vectors: list[list[float]] = []
    for src, vec in zip(sources, bookmark_vectors):
        if _source_key(src) in kept_keys:
            kept_vectors.append(vec)

    console.print(
        f"  [dim]Hard-blocked {len(dropped)} duplicate topic/source candidate(s).[/dim]"
    )
    for src, decision in dropped[:3]:
        preview = (src.get("text") or src.get("url") or "")[:80].replace("\n", " ")
        console.print(f"    [dim]- {decision.reason}: {preview}[/dim]")
    return kept_sources, kept_vectors


def _maybe_auto_sync_threads(cfg: "Config", db: DB) -> None:
    """Refresh published Threads posts if our local mirror is stale.

    Without this, dedup against "already published" posts uses whatever was in
    the DB at the last manual `orbit sync` — so anything posted today won't be
    caught even if it's in your feed. Runs the same _sync_threads used by the
    sync command, gracefully no-ops on any failure so drafting still works
    when offline or auth-expired.
    """
    try:
        last_pulled = db.conn.execute(
            "SELECT MAX(pulled_at) FROM metrics WHERE platform = 'threads'"
        ).fetchone()[0]
    except Exception:
        last_pulled = None

    if last_pulled:
        try:
            last_dt = datetime.fromisoformat(last_pulled.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - last_dt).total_seconds()
            if age < _AUTO_SYNC_STALE_SECONDS:
                return  # fresh enough
        except (ValueError, AttributeError):
            pass  # malformed timestamp → re-sync to be safe

    console.print("[dim]Refreshing Threads posts (so dedup sees today's posts)...[/dim]")
    try:
        from orbit.commands.sync import _sync_threads
        from orbit.patterns import PatternStore

        ps = PatternStore()
        now = datetime.now(timezone.utc).isoformat()
        _sync_threads(cfg, db, ps, now)
        console.print("  [dim]✓ Threads sync complete.[/dim]")
    except Exception as e:
        # Silent degradation — dedup still works, just against older data.
        console.print(f"  [yellow]⚠ Auto-sync skipped ({e}); using cached data.[/yellow]")


def _recent_published_threads_content(db: DB, limit: int = 50) -> list[str]:
    """Return content of recently committed Threads posts — published OR in the queue.

    "Committed" means any of: published (row in posts with non-empty published_at),
    scheduled locally, or handed off to Postiz. Without scheduled + handed_off,
    bookmarks you've already queued get re-suggested as fresh drafts (the original
    bug was 50 Postiz-queued posts invisible to dedup).

    Returns [] on any error so the calling dedup flow can no-op gracefully.
    """
    try:
        rows = db.conn.execute("""
            SELECT d.content
            FROM drafts d
            LEFT JOIN posts p
              ON p.draft_id = d.id AND p.platform = 'threads'
            WHERE d.platform = 'threads'
              AND d.content IS NOT NULL AND d.content != ''
              AND (
                (p.published_at IS NOT NULL AND p.published_at != '')
                OR d.status IN ('scheduled', 'handed_off_to_postiz')
              )
            ORDER BY COALESCE(d.publish_at, d.created_at) DESC
            LIMIT ?
        """, [limit]).fetchall()
        return [r[0] for r in rows if r[0]]
    except Exception:
        return []


def _recent_linkedin_formats(db: DB, limit: int = 3) -> list[str]:
    """Classify the format of the `limit` most-recent LinkedIn drafts.

    Returns format labels (STORY, TEARDOWN, CONTRARIAN, RESOURCE_DROP,
    QUESTION_DATA) in newest-first order. Used by the FORMAT FATIGUE GUARD
    in build_linkedin_prompt to avoid repeating formats LinkedIn's algo
    suppresses. Empty list on any error so the prompt degrades gracefully
    to "no fatigue guard" rather than failing draft generation.
    """
    try:
        from orbit.analysis import classify_linkedin_format
        rows = db.conn.execute("""
            SELECT content FROM drafts
            WHERE platform = 'linkedin'
              AND content IS NOT NULL AND content != ''
              AND status IN ('published', 'scheduled', 'handed_off_to_postiz', 'draft')
            ORDER BY COALESCE(publish_at, created_at) DESC
            LIMIT ?
        """, [limit]).fetchall()
        return [classify_linkedin_format(r[0]) for r in rows if r[0]]
    except Exception:
        return []


def _maybe_generate_linkedin(db: DB, ai, picked_sources: list[dict], now: str) -> list[int]:
    """Ask if user wants a LinkedIn variant. If yes, generate + show + save."""
    from orbit.analysis import build_linkedin_prompt

    if not picked_sources:
        return []
    choice = Prompt.ask(
        "Also draft a LinkedIn version from the same source? "
        "[cyan]y[/cyan]es / [cyan]Enter[/cyan] skip",
        default="",
    ).strip().lower()
    if choice not in ("y", "yes"):
        return []

    # Pull last 3 LinkedIn drafts, classify their formats, exclude those from the
    # menu so LinkedIn's algo doesn't suppress for "same format repeated". Mirror
    # of the Threads TOPIC FATIGUE GUARD pattern.
    recent_formats = _recent_linkedin_formats(db, limit=3)
    if recent_formats:
        console.print(
            f"  [dim]Recent LinkedIn formats: {', '.join(recent_formats)} "
            f"— will pick a different one.[/dim]"
        )

    console.print("[dim]Generating LinkedIn draft with Claude...[/dim]\n")
    prompt = build_linkedin_prompt(picked_sources, recent_formats=recent_formats)
    msg = ai.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()
    if not raw:
        console.print("[yellow]Claude returned an empty LinkedIn draft. Skipped.[/yellow]\n")
        return []

    console.print(Panel(raw, title="[bold cyan]LinkedIn draft[/bold cyan]", border_style="cyan"))
    save = Prompt.ask(
        "Save this LinkedIn draft? [cyan]y[/cyan]es / [cyan]Enter[/cyan] discard",
        default="",
    ).strip().lower()
    if save not in ("y", "yes"):
        console.print("[dim]LinkedIn draft discarded.[/dim]\n")
        return []

    import json as _json
    first_source = picked_sources[0]
    source_links = first_source.get("source_links") or []
    idea_id = db.conn["ideas"].insert({
        "title": raw[:80],
        "source": "draft:linkedin-variant",
        "status": "draft",
        "created_at": now,
    }).last_pk
    draft_id = db.conn["drafts"].insert({
        "idea_id": idea_id,
        "platform": "linkedin",
        "content": raw,
        "status": "draft",
        "source_url": first_source.get("url"),
        "media_url": first_source.get("media_url"),
        "media_type": first_source.get("media_type"),
        "source_links": _json.dumps(source_links) if source_links else None,
        "created_at": now,
    }).last_pk
    console.print(f"[green]✓ Saved LinkedIn draft #{draft_id}.[/green]\n")
    return [draft_id]


def _parse_picks(raw: str, n: int) -> list[int]:
    """Parse '1', '1,3', '1 3', '1, 3' into zero-based indices, deduped + ordered."""
    seen: set[int] = set()
    out: list[int] = []
    for tok in re.split(r"[,\s]+", raw.strip()):
        if not tok:
            continue
        if not tok.isdigit():
            return []
        idx = int(tok) - 1
        if 0 <= idx < n and idx not in seen:
            seen.add(idx)
            out.append(idx)
    return out


_TWEAK_RE = re.compile(r"^t\s*(\d+)\s+(.+)$", re.DOTALL)


def _parse_tweak(raw: str, n: int) -> tuple[int, str] | None:
    """Parse `t1 make it shorter` or `t 2 add a question` into (idx, feedback). Returns None if not a tweak."""
    m = _TWEAK_RE.match(raw.strip())
    if not m:
        return None
    idx = int(m.group(1)) - 1
    feedback = m.group(2).strip()
    if not (0 <= idx < n) or not feedback:
        return None
    return idx, feedback


def _parse_regenerate(raw: str, n: int) -> list[int] | None:
    """Parse `r` (all) or `r1` / `r1,3` / `r 2 3` into indices to regenerate.

    Returns None when input isn't a regenerate command, [] when `r` alone (regen all),
    or a list of zero-based indices for `r<n>` / `r<n>,<m>`.
    """
    s = raw.strip().lower()
    if s == "r":
        return list(range(n))  # regen all
    if not s.startswith("r"):
        return None
    tail = s[1:].strip()
    if not tail:
        return list(range(n))
    picks = _parse_picks(tail, n)
    return picks if picks else None


def _parse_dismiss(raw: str, n: int) -> list[int] | None:
    """Parse `d` (all) or `d1` / `d1,3` / `d 2 3` into indices to mark as done.

    Same shape as _parse_regenerate. Dismiss persistently marks the underlying
    bookmark as "already-posted/not-interesting" so it won't reappear in
    future draft sessions. Mirrors the regen UX so the two commands feel like
    siblings.
    """
    s = raw.strip().lower()
    if s == "d":
        return list(range(n))
    if not s.startswith("d"):
        return None
    tail = s[1:].strip()
    if not tail:
        return list(range(n))
    picks = _parse_picks(tail, n)
    return picks if picks else None


def _select_loop(
    drafts: list[str],
    ai: "anthropic.Anthropic",
    original_prompt: str,
    *,
    source_pool: list[dict] | None = None,
    used_source_keys: set[str] | None = None,
    top_patterns=None,
    recent_topics: list[str] | None = None,
    draft_sources: list[dict] | None = None,
    db: DB | None = None,
) -> list[int]:
    """Display drafts and loop: save picks, `t<n>` tweak one, `r` regenerate
    from fresh bookmarks, `d` dismiss bookmark(s) so they don't reappear.

    Optional kwargs:
    - source_pool, used_source_keys, top_patterns, recent_topics: enable `r`
    - draft_sources, db: enable `d` (need to persist dismissal to disk)
    """
    if used_source_keys is None:
        used_source_keys = set()
    can_regen = source_pool is not None and top_patterns is not None
    can_dismiss = draft_sources is not None and db is not None

    while True:
        console.print()
        for i, d in enumerate(drafts, 1):
            virality = _score_threads_draft_virality(d)
            title = (
                f"[bold cyan]Draft {i}[/bold cyan]  ·  "
                f"[bold {virality['color']}]Viral {virality['score']}/100 {virality['label']}[/bold {virality['color']}]"
            )
            console.print(Panel(d, title=title, border_style="cyan"))
            console.print(
                f"[dim]Score: {', '.join(virality['reasons'][:4])}[/dim]"
            )
            console.print()

        prompt_text = (
            "Save (e.g. [cyan]1[/cyan] or [cyan]1,3[/cyan])  ·  "
            "Tweak (e.g. [cyan]t2 make it shorter[/cyan])  ·  "
        )
        if can_regen:
            prompt_text += "Regen ([cyan]r[/cyan] all, [cyan]r1,3[/cyan] specific)  ·  "
        if can_dismiss:
            prompt_text += "Dismiss ([cyan]d1,3[/cyan] mark as done)  ·  "
        prompt_text += "[cyan]Enter[/cyan] to discard"
        choice = Prompt.ask(prompt_text, default="")

        tweak = _parse_tweak(choice, len(drafts))
        if tweak is not None:
            idx, feedback = tweak
            console.print(f"\n[dim]Reworking draft {idx + 1} with: {feedback!r}[/dim]")
            try:
                drafts[idx] = _tweak_draft(ai, original_prompt, drafts[idx], feedback)
            except Exception as e:
                console.print(f"[red]✗ Tweak failed: {e}[/red]")
            continue  # re-display all drafts, prompt again

        if can_dismiss:
            dismiss_indices = _parse_dismiss(choice, len(drafts))
            if dismiss_indices is not None:
                if not dismiss_indices:
                    console.print("[yellow]No valid draft indices to dismiss.[/yellow]")
                    continue
                dismissed_count = _dismiss_drafts(
                    db, draft_sources, dismiss_indices,
                )
                # Remove the dismissed drafts from view; if all are dismissed,
                # return empty picks (treated as discard).
                kept_indices = [i for i in range(len(drafts)) if i not in dismiss_indices]
                if not kept_indices:
                    console.print(
                        f"\n[dim]Dismissed {dismissed_count} bookmark(s). "
                        f"Nothing left — run `orbit draft` again for a fresh batch.[/dim]\n"
                    )
                    return []
                console.print(
                    f"\n[green]✓ Dismissed {dismissed_count} bookmark(s).[/green] "
                    f"[dim]They won't appear in future sessions.[/dim]"
                )
                drafts = [drafts[i] for i in kept_indices]
                draft_sources = [draft_sources[i] for i in kept_indices]
                continue

        if can_regen:
            regen_indices = _parse_regenerate(choice, len(drafts))
            if regen_indices is not None:
                if not regen_indices:
                    console.print("[yellow]No valid draft indices to regenerate.[/yellow]")
                    continue
                label = (
                    "all"
                    if len(regen_indices) == len(drafts)
                    else ", ".join(str(i + 1) for i in regen_indices)
                )
                console.print(
                    f"\n[dim]Regenerating draft(s) {label} from fresh bookmarks...[/dim]"
                )
                try:
                    drafts, used_source_keys = _regenerate_with_fresh_sources(
                        ai=ai,
                        top_patterns=top_patterns,
                        recent_topics=recent_topics or [],
                        source_pool=source_pool,
                        used_source_keys=used_source_keys,
                        current_drafts=drafts,
                        indices_to_regen=regen_indices,
                    )
                except RuntimeError as e:
                    console.print(f"[yellow]⚠ {e}[/yellow]")
                except Exception as e:
                    console.print(f"[red]✗ Regenerate failed: {e}[/red]")
                continue  # re-display all drafts, prompt again

        return _parse_picks(choice, len(drafts))


def _score_threads_draft_virality(draft: str) -> dict:
    """Heuristic Threads virality score for draft comparison in the picker.

    This is intentionally deterministic and cheap. It scores alignment with the
    same rules used in the prompt: broad AI-builder relevance, strong hook,
    concrete number, open/free signal, direct reader benefit, and red-line
    avoidance. It is not a promise of reach.
    """
    text = (draft or "").strip()
    if not text:
        return {
            "score": 0,
            "label": "low",
            "color": "red",
            "reasons": ["empty draft"],
        }

    score = 45
    reasons: list[str] = []
    lower = text.lower()
    compact = re.sub(r"\s+", " ", text)
    first_line = text.splitlines()[0].strip() if text.splitlines() else text
    last_line = next((line.strip() for line in reversed(text.splitlines()) if line.strip()), "")

    strong_hook = (
        first_line.startswith("有人")
        or first_line.lower().startswith("someone ")
        or bool(re.match(r"^[A-Z][A-Za-z0-9 .-]{1,32}\s+(剛|just|launched|released|open)", first_line))
    )
    if strong_hook:
        score += 14
        reasons.append("+ strong hook")
    else:
        score -= 8
        reasons.append("- soft hook")

    if re.search(r"\d", text):
        score += 12
        reasons.append("+ concrete number")
    else:
        score -= 10
        reasons.append("- no number")

    if any(sig in lower for sig in ("open source", "open-source", "github", "mit", "apache", "free", "開源", "免費")):
        score += 10
        reasons.append("+ open/free signal")

    if any(sig in lower for sig in ("省", "不用", "砍掉", "faster", "save", "minutes", "hours", "月費", "設定完")):
        score += 10
        reasons.append("+ reader benefit")
    elif last_line and any(obs in last_line for obs in ("不一樣", "新的預設", "AI 已經變了", "不是實驗等級")):
        score -= 8
        reasons.append("- observational ending")
    else:
        score -= 4
        reasons.append("- weak benefit")

    if any(sig in lower for sig in ("agent", "ai", "claude", "codex", "copilot", "gemini", "vllm")):
        score += 8
        reasons.append("+ AI-builder fit")

    char_count = len(compact)
    if 80 <= char_count <= 300:
        score += 8
        reasons.append("+ good length")
    elif char_count < 60:
        score -= 8
        reasons.append("- too short")
    elif char_count > 380:
        score -= 6
        reasons.append("- too long")

    if first_line.endswith("?") or first_line.endswith("？"):
        score -= 10
        reasons.append("- question hook")
    if first_line.startswith(("我", "I ")):
        score -= 8
        reasons.append("- starts with self")
    if any(sig in lower for sig in ("cookie", "researcher", "api users", "headless")):
        score -= 8
        reasons.append("- niche audience")

    score = max(0, min(100, score))
    if score >= 80:
        label, color = "high", "green"
    elif score >= 65:
        label, color = "medium", "yellow"
    else:
        label, color = "low", "red"
    return {
        "score": score,
        "label": label,
        "color": color,
        "reasons": reasons or ["no clear signals"],
    }


def _draft_topic(draft: str, source: dict | None) -> str:
    """Short topic slug for a draft, for Hermes' topic-variety reasoning.

    Prefers a brand/product name from the source bookmark; falls back to the
    draft's first line trimmed. Not a precise classifier — just enough signal
    for an agent to notice 'these two are the same story'.
    """
    if source:
        for key in ("title", "text"):
            val = (source.get(key) or "").strip()
            if val:
                return val[:60]
    first = (draft or "").strip().splitlines()
    return first[0][:60] if first else ""


def _exit_empty(json_out: bool, json_stream, db: "DB") -> "typing.NoReturn":
    """End generation with no drafts.

    In --json mode (Hermes), emit a valid empty payload to stdout and exit 0 —
    "nothing to post today" is a normal outcome, not an error, so the agent can
    parse `{"candidates": []}` and move on. Interactive mode keeps exiting 1.
    """
    if json_out:
        import json as _json
        import sys as _sys
        payload = build_draft_json_payload(
            [], [], [],
            recent_topics=_recent_threads_topics(db, limit=5),
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        out = json_stream if json_stream is not None else _sys.stdout
        print(_json.dumps(payload, ensure_ascii=False, indent=2), file=out)
        raise typer.Exit(0)
    raise typer.Exit(1)


def build_draft_json_payload(
    drafts: list[str],
    sources: list[dict],
    saved_ids: list[int],
    *,
    recent_topics: list[str],
    generated_at: str,
) -> dict:
    """Shape generated drafts + scores into the JSON Hermes reads off stdout.

    Pure: no DB, no network. Emits one candidate per SAVED id (a draft that was
    blocked/not saved is simply omitted), pairing ids to drafts positionally.
    """
    candidates = []
    for i, draft_id in enumerate(saved_ids):
        if i >= len(drafts):
            break
        text = drafts[i]
        score = _score_threads_draft_virality(text)
        source = sources[i] if i < len(sources) else None
        candidates.append({
            "draft_id": draft_id,
            "score": score["score"],
            "label": score["label"],
            "topic": _draft_topic(text, source),
            "text": text,
            "signals": score["reasons"],
        })
    return {
        "generated_at": generated_at,
        "recent_topics": recent_topics,
        "candidates": candidates,
    }


def _dismiss_drafts(db: DB, draft_sources: list[dict], indices: list[int]) -> int:
    """Persist the bookmarks behind these draft slots as 'dismissed' on disk.

    Returns count of newly-dismissed sources (ignoring no-ops for sources
    already in the table).
    """
    added = 0
    for idx in indices:
        if idx < 0 or idx >= len(draft_sources):
            continue
        src = draft_sources[idx]
        if not src:
            continue
        if _add_dismissed_source(db, src):
            added += 1
    return added


def _source_key(source: dict) -> str:
    """Stable identifier for a bookmark — URL when present, else hash of text.

    Used to track which bookmarks have already been drawn from in the current
    session so regenerate doesn't pull the same source twice.
    """
    if not source:
        return ""
    url = source.get("url")
    if url:
        return f"url:{url}"
    text = source.get("text") or ""
    return f"text:{hash(text)}"


def _regenerate_with_fresh_sources(
    *,
    ai: "anthropic.Anthropic",
    top_patterns,
    recent_topics: list[str],
    source_pool: list[dict],
    used_source_keys: set[str],
    current_drafts: list[str],
    indices_to_regen: list[int],
) -> tuple[list[str], set[str]]:
    """Replace specified draft slots with fresh drafts generated from unused bookmarks.

    Picks the next N bookmarks from `source_pool` whose keys aren't in
    `used_source_keys`, builds a one-shot prompt, parses the response, and
    swaps the new drafts into the requested slots.

    Raises RuntimeError when the pool is exhausted or Claude returns too few
    drafts — caller catches and shows a friendly message.
    """
    needed = len(indices_to_regen)
    fresh_sources: list[dict] = []
    for s in source_pool:
        if _source_key(s) in used_source_keys:
            continue
        fresh_sources.append(s)
        if len(fresh_sources) == needed:
            break

    if len(fresh_sources) < needed:
        if not fresh_sources:
            raise RuntimeError(
                "No unused bookmarks left in the ranked pool. "
                "Run `orbit draft -r` to fetch fresh bookmarks from X."
            )
        raise RuntimeError(
            f"Only {len(fresh_sources)} unused bookmark(s) available, "
            f"but {needed} draft(s) requested. Regen fewer at a time, "
            f"or run `orbit draft -r` for more."
        )

    # Build a fresh one-shot prompt limited to the new sources. The pattern
    # prompt will ask for exactly len(fresh_sources) drafts back, matching
    # what we need to fill the regen slots.
    fresh_prompt = build_pattern_prompt(
        top_patterns,
        fresh_sources,
        recent_topics=recent_topics,
        count=needed,
    )
    msg = ai.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": fresh_prompt}],
    )
    new_drafts = _parse_drafts(msg.content[0].text)
    if len(new_drafts) < needed:
        raise RuntimeError(
            f"Claude returned only {len(new_drafts)} draft(s) for {needed} "
            f"slot(s). Try regenerating again."
        )

    out = list(current_drafts)
    new_used = set(used_source_keys)
    for slot, new_draft, src in zip(indices_to_regen, new_drafts[:needed], fresh_sources):
        out[slot] = new_draft
        new_used.add(_source_key(src))

    return out, new_used


def _tweak_draft(ai: "anthropic.Anthropic", original_prompt: str, current: str, feedback: str) -> str:
    """Ask Claude to rework one draft given the user's feedback. Returns the new text."""
    tweak_prompt = f"""You previously wrote this Threads post for Keith:

{current}

Keith's feedback: {feedback}

Rewrite the post applying his feedback. Keep his tone (short punchy sentences, hook + payoff, Traditional Chinese + English mix). Output ONLY the rewritten post — no explanation, no numbering, no quotes around it."""
    msg = ai.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[
            {"role": "user", "content": original_prompt},
            {"role": "assistant", "content": "(previous drafts shown)"},
            {"role": "user", "content": tweak_prompt},
        ],
    )
    return msg.content[0].text.strip()


def _best_source_match(draft_text: str, sources: list[dict]) -> dict | None:
    """Pick the source bookmark this draft is most likely about, by overlap of
    distinctive tokens (5+ char ASCII words and brand-like tokens).

    Returns None if no source has even a single distinctive token in common —
    so caller can fall back to a default rather than picking a random match.
    """
    if not sources:
        return None
    draft_tokens = _distinctive_tokens(draft_text)
    if not draft_tokens:
        return None
    best: tuple[int, dict] | None = None
    for s in sources:
        src_text = s.get("text") or ""
        overlap = len(draft_tokens & _distinctive_tokens(src_text))
        if best is None or overlap > best[0]:
            best = (overlap, s)
    if best is None or best[0] == 0:
        return None
    return best[1]


_TOKEN_RE = re.compile(r"[a-z][a-z0-9]+\.[a-z][a-z0-9]+|[a-z]{5,}", re.IGNORECASE)
_TOKEN_NOISE = {
    "about", "after", "again", "always", "another", "because", "before",
    "being", "between", "called", "company", "could", "every", "first",
    "going", "should", "their", "there", "these", "thing", "those", "today",
    "which", "while", "would",
}


def _distinctive_tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "") if t.lower() not in _TOKEN_NOISE}


def _parse_drafts(text: str) -> list[str]:
    """Split Claude's response into individual drafts.

    Handles [1] through [9] so the same parser works for the default 3-draft
    flow and the expanded 6-draft flow.
    """
    parts = re.split(r"\[([1-9])\]", text)
    drafts = []
    for i in range(1, len(parts), 2):
        content = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if content:
            drafts.append(content)
    return drafts


def _post_save_action(db: DB, draft_ids: list[int], contents: list[str], cfg: Config) -> None:
    """After save: offer to post now, schedule, or leave as draft."""
    console.print(
        "[bold]What next?[/bold]  [cyan]p[/cyan]ost now  ·  [cyan]s[/cyan]chedule  ·  [cyan]Enter[/cyan] keep as draft"
    )
    action = Prompt.ask("Choose", default="").strip().lower()

    if action in ("p", "post", "post now"):
        _publish_now(db, draft_ids, contents, cfg)
    elif action in ("s", "schedule"):
        _schedule(db, draft_ids)
    else:
        console.print(
            f"\n[dim]Kept as draft. View later with[/dim] [cyan]orbit drafts list[/cyan][dim].[/dim]\n"
        )


def _publish_now(db: DB, draft_ids: list[int], contents: list[str], cfg: Config) -> None:
    token = cfg.get("threads.access_token")
    user_id = cfg.get("threads.user_id")
    if not token or not user_id:
        console.print(
            "\n[red]✗ Threads not configured.[/red] Run: [cyan]orbit setup --platform threads[/cyan]\n"
        )
        return

    client = ThreadsClient(access_token=token, user_id=user_id)
    now = datetime.now(timezone.utc).isoformat()
    for draft_id, content in zip(draft_ids, contents):
        try:
            console.print(f"  [dim]Publishing draft {draft_id}...[/dim]")
            thread_id = client.create_post(content)
        except Exception as e:
            console.print(f"  [red]✗ Draft {draft_id} failed: {e}[/red]")
            continue
        db.conn["drafts"].update(draft_id, {"status": "published"})
        db.conn["posts"].insert({
            "draft_id": draft_id,
            "platform": "threads",
            "external_id": thread_id,
            "published_at": now,
        })
        console.print(f"  [green]✓ Posted: https://www.threads.net/@you/post/{thread_id}[/green]")
    console.print()


def _schedule(db: DB, draft_ids: list[int]) -> None:
    """Per-draft slot picker. After picking a slot, auto-hand-off to Postiz so the
    post actually reaches Threads + Facebook. Handoff failures are non-fatal —
    the draft stays scheduled locally and the user can retry with
    `orbit drafts handoff <id>`."""
    from orbit.commands.drafts import do_handoff

    scheduled_locally = 0
    handed_off = 0
    handoff_failures: list[tuple[int, str]] = []

    for i, draft_id in enumerate(draft_ids, 1):
        if len(draft_ids) > 1:
            console.print(f"\n[bold]Draft {draft_id}[/bold]  ([dim]{i} of {len(draft_ids)}[/dim])")
        slot_iso = _pick_slot(db)
        if slot_iso is None:
            console.print(f"  [dim]Skipped — draft {draft_id} stays as `draft`.[/dim]")
            continue

        # 1. Write the slot to the local DB. This sets up the row for handoff to read.
        db.conn["drafts"].update(draft_id, {"status": "scheduled", "publish_at": slot_iso})
        scheduled_locally += 1

        # 2. Hand off to Postiz. If it fails (Postiz down, auth expired, network),
        #    log it but leave the draft scheduled locally so the user can retry.
        console.print(f"  [dim]Handing off to Postiz...[/dim]")
        result = do_handoff(draft_id)
        if result.ok:
            console.print(f"  [green]✓[/green] {result.message}")
            handed_off += 1
        else:
            console.print(f"  [yellow]⚠ Postiz handoff failed:[/yellow] {result.message}")
            console.print(
                f"  [dim]Draft is scheduled locally. Retry with[/dim] "
                f"[cyan]orbit drafts handoff {draft_id}[/cyan]"
            )
            handoff_failures.append((draft_id, result.message))

    # Summary
    if scheduled_locally == 0:
        console.print()
        return

    console.print()
    if handed_off == scheduled_locally:
        console.print(f"[green]✓ {handed_off} draft(s) scheduled on Postiz.[/green] "
                      f"[dim]View at https://postiz.com.[/dim]\n")
    elif handed_off > 0:
        console.print(
            f"[yellow]Partial:[/yellow] {handed_off}/{scheduled_locally} reached Postiz. "
            f"{len(handoff_failures)} stuck locally — retry with "
            f"[cyan]orbit drafts handoff <id>[/cyan].\n"
        )
    else:
        console.print(
            f"[red]Scheduled locally but NOT on Postiz.[/red] "
            f"Retry each with [cyan]orbit drafts handoff <id>[/cyan]:\n"
        )
        for did, msg in handoff_failures:
            console.print(f"  [cyan]orbit drafts handoff {did}[/cyan]  [dim]({msg})[/dim]")
        console.print()


def _pick_slot(db: DB) -> str | None:
    """Show the next 9am/4pm/9pm HKT slots that aren't already taken. Return UTC ISO or None."""
    from orbit.scheduling import format_slot, next_slots

    now = datetime.now(timezone.utc)
    taken = {
        r["publish_at"]
        for r in db.conn.query("SELECT publish_at FROM drafts WHERE status = 'scheduled' AND publish_at IS NOT NULL")
    }
    slots = next_slots(now, taken, count=5)

    if not slots:
        console.print("  [yellow]Couldn't find a free slot in the next 14 days.[/yellow]")
        return None

    console.print("  When?")
    for i, slot in enumerate(slots, 1):
        console.print(f"    [cyan]{i}[/cyan]  {format_slot(slot, now)}")
    console.print(f"    [cyan]c[/cyan]  custom (ISO, e.g. 2026-05-23T09:00:00Z)")
    console.print(f"    [cyan]Enter[/cyan]  skip this draft")

    choice = Prompt.ask("  Pick", default="").strip().lower()

    if choice == "":
        return None
    if choice == "c":
        raw = Prompt.ask("  Custom ISO timestamp", default="").strip()
        if not raw:
            return None
        try:
            when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            console.print(f"  [red]✗ Could not parse '{raw}'.[/red]")
            return None
        return when.astimezone(timezone.utc).isoformat()
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(slots):
            return slots[idx].astimezone(timezone.utc).isoformat()
    console.print(f"  [yellow]Invalid choice '{choice}'. Skipped.[/yellow]")
    return None
