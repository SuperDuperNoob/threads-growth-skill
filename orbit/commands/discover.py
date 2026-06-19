"""orbit discover — fetch + score X candidates from your For You feed."""
from __future__ import annotations
from datetime import datetime, timezone
import json
import os

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from orbit.config import Config
from orbit.db import DB
from orbit.duplicates import check_duplicate, filter_duplicate_sources, record_content
from orbit.discovery import score_candidate
from orbit.platforms.twitter import TwitterClient

app = typer.Typer(help="Find X content matching your audience profile")
console = Console()


@app.callback(invoke_without_command=True)
def discover(
    ctx: typer.Context,
    limit: int = typer.Option(
        50, "--limit", "-n", help="Max tweets to pull from your For You feed"
    ),
    show: int = typer.Option(
        10, "--show", "-s", help="How many top candidates to display"
    ),
    refresh: bool = typer.Option(
        False, "--refresh", "-r",
        help="Re-fetch even tweets we've already seen (otherwise we skip known tweet_ids)",
    ),
) -> None:
    """Pull your For You feed from X, score against your audience profile, show top picks.

    Your X feed already reflects years of training (who you follow, what you like).
    We score each tweet on brand-name AI mentions, open-source signals, freshness,
    engagement, and novelty vs. your existing posts.
    """
    # When a subcommand (draft/autofill) is invoked, skip the feed pull entirely.
    # The callback otherwise re-pulls the live For You feed on every `discover
    # draft` call, which re-ranks the stored picks and makes rank numbers point
    # at different tweets than the user just saw.
    if ctx.invoked_subcommand is not None:
        return

    cfg = Config()
    cookies_path = cfg.get("twitter.cookies_path")
    if not cookies_path:
        console.print(
            "\n[red]✗ Twitter not configured.[/red] Run: "
            "[cyan]orbit setup --platform twitter[/cyan]\n"
        )
        raise typer.Exit(1)

    db = DB()

    console.print(f"\n[bold]Pulling your For You feed...[/bold]")
    client = TwitterClient(cookies_path=cookies_path)
    try:
        candidates = client.get_home_timeline(limit=limit)
    except Exception as e:
        console.print(f"\n[red]✗ Failed to fetch feed: {e}[/red]\n")
        raise typer.Exit(1)
    console.print(f"  [green]✓[/green] Pulled {len(candidates)} tweets")

    # Skip tweets we've already stored (unless --refresh)
    if not refresh:
        seen = {r["tweet_id"] for r in db.conn["discoveries"].rows}
        candidates = [c for c in candidates if c.get("tweet_id") not in seen]
        console.print(f"  [dim]{len(candidates)} new since last run[/dim]")

    if not candidates:
        console.print("\n[yellow]No new candidates.[/yellow] "
                      "Try [cyan]orbit discover --refresh[/cyan] to re-score known tweets.\n")
        raise typer.Exit()

    # Score against your recent posts (for novelty penalty)
    existing = [
        r["content"] or ""
        for r in db.conn.query(
            "SELECT content FROM drafts WHERE platform='threads' "
            "AND content IS NOT NULL ORDER BY id DESC LIMIT 50"
        )
    ]

    scored = []
    now = datetime.now(timezone.utc)
    candidates, duplicate_drops = filter_duplicate_sources(db, candidates)
    if duplicate_drops:
        console.print(
            f"  [dim]Hard-blocked {len(duplicate_drops)} already-covered topic/source candidate(s).[/dim]"
        )
    for c in candidates:
        result = score_candidate(c, existing_topics=existing, now=now)
        # Hard filter: require at least one positive topic signal (brand-name AI,
        # open-source, or launch). Without this, viral non-AI feed noise floods
        # the rankings purely on engagement + freshness.
        has_topic_signal = any(
            "brand-name AI" in r or "open-source" in r or "launch signal" in r
            for r in result.reasoning
        )
        if not has_topic_signal:
            continue
        scored.append((result.score, result.reasoning, c))

    scored.sort(key=lambda t: -t[0])
    top = scored[:show]
    if not top:
        console.print(
            "\n[yellow]No AI/dev candidates in this batch.[/yellow] "
            "Your feed had viral content but nothing matched a brand-name AI, "
            "open-source, or launch signal. Try [cyan]--limit 200[/cyan] for a wider pull.\n"
        )
        raise typer.Exit()

    # Persist all candidates (top and not-top) so we don't re-score next run
    _persist(db, scored, now)

    # Display top picks
    console.print()
    for i, (score, reasoning, c) in enumerate(top, 1):
        color = "green" if score >= 50 else "yellow" if score >= 25 else "dim"
        media = c.get("media_type")
        media_str = f" [{c.get('media_type')}]" if media else ""
        header = (
            f"[bold {color}][{i}]  {score}/100[/bold {color}]  "
            f"{c['author']}{media_str}  ·  {c['url']}"
        )
        reasons = "\n".join(f"  [dim]·[/dim] {r}" for r in reasoning) or "  [dim]· (no signal hits)[/dim]"
        body = c["text"]
        if len(body) > 280:
            body = body[:277] + "…"
        console.print(Panel(
            f"{body}\n\n{reasons}",
            title=header,
            border_style=color,
        ))
        console.print()

    console.print(
        f"[dim]To turn picks into Threads drafts, run[/dim] "
        f"[cyan]orbit discover draft 1,3,5[/cyan]  [dim](or any combo from above).[/dim]\n"
    )


@app.command("draft")
def draft_from_discoveries(
    picks: str = typer.Argument(..., help="Comma-separated rank numbers from `orbit discover` (e.g. 1,3,5)"),
    json_out: bool = typer.Option(
        False, "--json",
        help="Non-interactive: generate, score, save drafts, print JSON to stdout. "
             "No prompts. For agent/headless use (Hermes).",
    ),
) -> None:
    """Convert ranked discoveries into Threads drafts via Claude."""
    from orbit.commands.draft import _run_draft_generation  # lazy: avoids circular import on cold load

    # In JSON mode all human-facing status goes to stderr so stdout carries
    # only the final JSON payload that Hermes parses.
    status = Console(stderr=True) if json_out else console

    db = DB()
    indices = _parse_int_list(picks)
    if not indices:
        status.print(f"\n[red]Could not parse '{picks}'.[/red] Use e.g. [cyan]1,3,5[/cyan].\n")
        raise typer.Exit(1)

    # Pull the most recently displayed top picks. We persist them with status='new'
    # and ordered by created_at DESC, then by score DESC within the latest batch.
    rows = list(db.conn.query(
        "SELECT id, tweet_id, url, text, author, media_url, media_type, source_links "
        "FROM discoveries WHERE status = 'new' ORDER BY score DESC LIMIT 50"
    ))
    if not rows:
        status.print("\n[yellow]No fresh discoveries.[/yellow] "
                     "Run [cyan]orbit discover[/cyan] first.\n")
        raise typer.Exit(1)

    chosen = [rows[i - 1] for i in indices if 1 <= i <= len(rows)]
    if not chosen:
        status.print(f"\n[red]None of {picks} are in range 1..{len(rows)}.[/red]\n")
        raise typer.Exit(1)

    # Reshape into the bookmark-like dicts that draft.py knows how to consume
    fake_bookmarks = [{
        "text": r["text"],
        "author": r["author"],
        "url": r["url"],
        "media_url": r.get("media_url"),
        "media_type": r.get("media_type"),
        "source_links": _loads_json_list(r.get("source_links")),
    } for r in chosen]

    status.print(f"\n[dim]Generating Threads drafts from {len(chosen)} discoveries...[/dim]\n")
    if json_out:
        # Same stdout discipline as `orbit draft --json`: redirect ALL stdout to
        # stderr during generation so only the JSON payload lands on real stdout.
        import sys
        from contextlib import redirect_stdout
        real_stdout = sys.stdout
        with redirect_stdout(sys.stderr):
            _run_draft_generation(fake_bookmarks, json_out=True, json_stream=real_stdout)
    else:
        _run_draft_generation(fake_bookmarks)

    # Mark the chosen ones as drafted so they don't re-appear
    for r in chosen:
        db.conn["discoveries"].update(r["id"], {"status": "drafted"})


@app.command("autofill")
def autofill(
    count: int = typer.Option(3, "--count", "-c", help="How many Threads posts to schedule"),
    feed_limit: int = typer.Option(120, "--feed-limit", help="Tweets to pull from your X For You feed"),
    account_limit: int = typer.Option(6, "--accounts", help="How many curated accounts to scan"),
    tweets_per_account: int = typer.Option(15, "--tweets-per-account", help="Tweets to pull per curated account"),
    min_score: int = typer.Option(35, "--min-score", help="Minimum discovery score before drafting"),
    postiz_draft: bool = typer.Option(False, "--postiz-draft", help="Create Postiz drafts instead of scheduled posts"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show selected candidates without generating/scheduling"),
) -> None:
    """Find, draft, and schedule the next HKT posting slots.

    Sources: your X For You feed, curated AI/dev accounts, and optional Apify
    results when APIFY_TOKEN + APIFY_ACTOR_ID are configured.
    """
    cfg = Config()
    db = DB()
    candidates = collect_candidates(
        cfg,
        feed_limit=feed_limit,
        account_limit=account_limit,
        tweets_per_account=tweets_per_account,
    )
    if not candidates:
        console.print("\n[yellow]No candidates collected.[/yellow]\n")
        raise typer.Exit(1)

    selected = select_autofill_sources(
        db,
        candidates,
        min_score=min_score,
        count=max(count * 3, count + 4),
    )
    if not selected:
        console.print("\n[yellow]No candidates survived scoring + duplicate checks.[/yellow]\n")
        raise typer.Exit(1)

    console.print(f"\n[bold]Selected {min(len(selected), count)} source candidate(s):[/bold]\n")
    for i, source in enumerate(selected[:count], 1):
        console.print(Panel(
            (source.get("text") or "")[:360],
            title=f"[bold cyan]{i}. {source.get('author')} · score {source.get('_score')}[/bold cyan]",
            border_style="cyan",
        ))

    if dry_run:
        console.print("[dim]Dry run only; no drafts generated.[/dim]\n")
        return

    drafts = generate_autofill_drafts(db, cfg, selected, count=count)
    if not drafts:
        console.print("\n[yellow]Claude did not return usable drafts.[/yellow]\n")
        raise typer.Exit(1)

    saved_ids = save_and_schedule_autofill(
        db,
        drafts,
        selected,
        postiz_draft=postiz_draft,
    )
    if not saved_ids:
        console.print("\n[red]No drafts scheduled; duplicate gate blocked every generated draft.[/red]\n")
        raise typer.Exit(1)
    console.print(f"\n[green]✓ Autofill saved {len(saved_ids)} draft(s).[/green]\n")


# --- helpers ---


def collect_candidates(
    cfg: Config,
    *,
    feed_limit: int,
    account_limit: int,
    tweets_per_account: int,
) -> list[dict]:
    """Collect candidate tweets from configured providers."""
    cookies_path = cfg.get("twitter.cookies_path")
    if not cookies_path:
        console.print(
            "\n[red]✗ Twitter not configured.[/red] Run: "
            "[cyan]orbit setup --platform twitter[/cyan]\n"
        )
        raise typer.Exit(1)

    client = TwitterClient(cookies_path=cookies_path)
    out: list[dict] = []

    console.print("\n[bold]Collecting candidates...[/bold]")
    try:
        feed = client.get_home_timeline(limit=feed_limit)
        console.print(f"  [green]✓[/green] X For You: {len(feed)}")
        out.extend(feed)
    except Exception as e:
        console.print(f"  [yellow]⚠ X For You skipped: {e}[/yellow]")

    if account_limit > 0:
        try:
            from orbit.curated import ALL as CURATED_ACCOUNTS
            for handle in CURATED_ACCOUNTS[:account_limit]:
                try:
                    tweets = client.get_user_tweets(handle, limit=tweets_per_account)
                except Exception as e:
                    console.print(f"  [dim]@{handle} skipped: {e}[/dim]")
                    continue
                console.print(f"  [green]✓[/green] @{handle}: {len(tweets)}")
                out.extend(tweets)
        except Exception as e:
            console.print(f"  [yellow]⚠ curated accounts skipped: {e}[/yellow]")

    apify = collect_apify_candidates(cfg)
    if apify:
        console.print(f"  [green]✓[/green] Apify: {len(apify)}")
        out.extend(apify)

    deduped: dict[str, dict] = {}
    for item in out:
        key = item.get("tweet_id") or item.get("url") or item.get("text")
        if key and key not in deduped:
            deduped[key] = item
    console.print(f"  [dim]{len(deduped)} unique candidate(s)[/dim]")
    return list(deduped.values())


def collect_apify_candidates(cfg: Config) -> list[dict]:
    """Optional generic Apify actor hook.

    Configure either env vars or config keys:
    - APIFY_TOKEN / apify.token
    - APIFY_ACTOR_ID / apify.actor_id
    - APIFY_ACTOR_INPUT_JSON / apify.input
    """
    token = os.environ.get("APIFY_TOKEN") or cfg.get("apify.token")
    actor_id = os.environ.get("APIFY_ACTOR_ID") or cfg.get("apify.actor_id")
    if not token or not actor_id:
        return []
    raw_input = os.environ.get("APIFY_ACTOR_INPUT_JSON") or cfg.get("apify.input")
    try:
        actor_input = json.loads(raw_input) if isinstance(raw_input, str) and raw_input else (raw_input or {})
    except json.JSONDecodeError:
        console.print("  [yellow]⚠ APIFY_ACTOR_INPUT_JSON is invalid JSON; Apify skipped.[/yellow]")
        return []
    try:
        import httpx
        url = f"https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items"
        resp = httpx.post(url, params={"token": token}, json=actor_input, timeout=180)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        console.print(f"  [yellow]⚠ Apify skipped: {e}[/yellow]")
        return []
    if not isinstance(data, list):
        return []
    return [_normalize_apify_item(item) for item in data if isinstance(item, dict)]


def _normalize_apify_item(item: dict) -> dict:
    text = item.get("text") or item.get("full_text") or item.get("content") or ""
    author = item.get("author") or item.get("username") or item.get("userName") or ""
    if isinstance(author, dict):
        author = author.get("userName") or author.get("screenName") or author.get("name") or ""
    author = f"@{str(author).lstrip('@')}" if author else "@unknown"
    url = item.get("url") or item.get("tweetUrl") or item.get("twitterUrl")
    tweet_id = str(item.get("id") or item.get("tweetId") or "")
    media_url = item.get("media_url") or item.get("mediaUrl")
    media_type = item.get("media_type") or item.get("mediaType")
    media = item.get("media") or item.get("extendedEntities") or []
    if not media_url and isinstance(media, list) and media:
        first = media[0] if isinstance(media[0], dict) else {}
        media_url = first.get("url") or first.get("media_url_https") or first.get("mediaUrl")
        media_type = first.get("type") or media_type
    return {
        "text": text,
        "author": author,
        "url": url,
        "tweet_id": tweet_id,
        "media_url": media_url,
        "media_type": media_type,
        "source_links": item.get("source_links") or item.get("urls") or [],
        "source_likes": int(item.get("likeCount") or item.get("likes") or item.get("favorite_count") or 0),
        "source_retweets": int(item.get("retweetCount") or item.get("retweets") or 0),
        "source_views": int(item.get("viewCount") or item.get("views") or 0),
        "created_at": item.get("createdAt") or item.get("created_at"),
    }


def select_autofill_sources(
    db: DB,
    candidates: list[dict],
    *,
    min_score: int,
    count: int,
) -> list[dict]:
    existing = [
        r["content"] or ""
        for r in db.conn.query(
            "SELECT content FROM drafts WHERE platform='threads' "
            "AND content IS NOT NULL ORDER BY id DESC LIMIT 500"
        )
    ]
    candidates, duplicate_drops = filter_duplicate_sources(db, candidates)
    if duplicate_drops:
        console.print(f"  [dim]Hard-blocked {len(duplicate_drops)} duplicate candidate(s).[/dim]")

    scored: list[dict] = []
    now = datetime.now(timezone.utc)
    for c in candidates:
        result = score_candidate(c, existing_topics=existing, now=now)
        has_topic_signal = any(
            "brand-name AI" in r or "open-source" in r or "launch signal" in r
            for r in result.reasoning
        )
        if not has_topic_signal or result.score < min_score:
            continue
        if not c.get("media_url"):
            continue
        c = dict(c)
        c["_score"] = result.score
        c["_reasoning"] = result.reasoning
        scored.append(c)

    scored.sort(key=lambda c: int(c.get("_score") or 0), reverse=True)
    return scored[:count]


def generate_autofill_drafts(
    db: DB,
    cfg: Config,
    sources: list[dict],
    *,
    count: int,
) -> list[str]:
    import anthropic
    from orbit.analysis import build_pattern_prompt, extract_top_patterns
    from orbit.commands.draft import _parse_drafts, _recent_threads_performance, _recent_threads_topics

    api_key = os.environ.get("ANTHROPIC_API_KEY") or cfg.get("anthropic.api_key")
    if not api_key:
        console.print("\n[red]✗ ANTHROPIC_API_KEY not set.[/red]\n")
        raise typer.Exit(1)

    rows = db.conn.execute("""
        SELECT d.content, m.views, m.likes
        FROM posts p
        JOIN drafts d ON d.id = p.draft_id
        JOIN metrics m ON m.post_id = p.id
        WHERE p.platform='threads' AND m.views IS NOT NULL
        ORDER BY m.views DESC
        LIMIT 10
    """).fetchall()
    top_posts = [{"content": r[0], "views": r[1], "likes": r[2]} for r in rows]
    top_patterns = extract_top_patterns(top_posts, top_n=5)
    prompt = build_pattern_prompt(
        top_patterns,
        sources,
        recent_topics=_recent_threads_topics(db, limit=5),
        recent_performance=_recent_threads_performance(db, limit=7),
        count=min(count, len(sources)),
    )
    ai = anthropic.Anthropic(api_key=api_key)
    msg = ai.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_drafts(msg.content[0].text)


def save_and_schedule_autofill(
    db: DB,
    drafts: list[str],
    sources: list[dict],
    *,
    postiz_draft: bool,
) -> list[int]:
    from orbit.commands.draft import _best_source_match
    from orbit.commands.drafts import do_handoff
    from orbit.scheduling import next_slots

    taken = {
        r["publish_at"]
        for r in db.conn.query(
            "SELECT publish_at FROM drafts WHERE publish_at IS NOT NULL "
            "AND status IN ('scheduled', 'handed_off_to_postiz')"
        )
    }
    slots = next_slots(datetime.now(timezone.utc), taken, count=len(drafts))
    saved: list[int] = []
    now = datetime.now(timezone.utc).isoformat()
    for draft_text, slot in zip(drafts, slots):
        source = _best_source_match(draft_text, sources) or (sources[0] if sources else {})
        duplicate = check_duplicate(db, content=draft_text, source=source)
        if duplicate.is_duplicate:
            console.print(
                f"  [yellow]⚠ Duplicate blocked ({duplicate.reason}; "
                f"matched draft {duplicate.matched_draft_id}).[/yellow]"
            )
            continue
        idea_id = db.conn["ideas"].insert({
            "title": draft_text[:80],
            "source": "autofill",
            "status": "draft",
            "created_at": now,
        }).last_pk
        source_links = source.get("source_links") or []
        draft_id = db.conn["drafts"].insert({
            "idea_id": idea_id,
            "platform": "threads",
            "content": draft_text,
            "status": "scheduled",
            "publish_at": slot.astimezone(timezone.utc).isoformat(),
            "source_url": source.get("url"),
            "media_url": source.get("media_url"),
            "media_type": source.get("media_type"),
            "source_links": json.dumps(source_links) if source_links else None,
            "created_at": now,
        }).last_pk
        record_content(
            db,
            draft_id=draft_id,
            content=draft_text,
            source=source,
            status="scheduled",
        )
        result = do_handoff(draft_id, as_draft=postiz_draft)
        if result.ok:
            console.print(f"  [green]✓[/green] {result.message}")
        else:
            console.print(f"  [yellow]⚠ Postiz handoff failed for {draft_id}: {result.message}[/yellow]")
        saved.append(draft_id)
    return saved


def _persist(db: DB, scored: list, now: datetime) -> None:
    """Upsert each scored candidate into the discoveries table."""
    now_iso = now.isoformat()
    for score, reasoning, c in scored:
        # Skip duplicates via the unique index on tweet_id
        existing = list(db.conn["discoveries"].rows_where("tweet_id = ?", [c.get("tweet_id")]))
        if existing:
            # Update score in case it changed (e.g., engagement grew)
            db.conn["discoveries"].update(existing[0]["id"], {
                "score": score,
                "score_reasoning": "\n".join(reasoning),
                "source_links": json.dumps(c.get("source_links") or []),
                "media_url": c.get("media_url"),
                "media_type": c.get("media_type"),
                "fetched_at": now_iso,
            })
            continue
        db.conn["discoveries"].insert({
            "tweet_id": c.get("tweet_id"),
            "author": c.get("author"),
            "url": c.get("url"),
            "text": c.get("text"),
                "media_url": c.get("media_url"),
                "media_type": c.get("media_type"),
                "source_links": json.dumps(c.get("source_links") or []),
                "source_likes": c.get("source_likes") or 0,
                "source_retweets": c.get("source_retweets") or 0,
            "source_views": c.get("source_views") or 0,
            "score": score,
            "score_reasoning": "\n".join(reasoning),
            "fetched_at": now_iso,
            "status": "new",
        })


def _parse_int_list(raw: str) -> list[int]:
    """'1,3,5' -> [1,3,5]. '1 3 5' also works. Drops non-numeric tokens."""
    import re
    out: list[int] = []
    for tok in re.split(r"[,\s]+", raw.strip()):
        if tok.isdigit():
            out.append(int(tok))
    return out


def _loads_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return data if isinstance(data, list) else []
