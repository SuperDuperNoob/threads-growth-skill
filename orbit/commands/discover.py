"""orbit discover — fetch + score X candidates from your For You feed."""
from __future__ import annotations
from datetime import datetime, timezone

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from orbit.config import Config
from orbit.db import DB
from orbit.discovery import score_candidate
from orbit.platforms.twitter import TwitterClient

app = typer.Typer(help="Find X content matching your audience profile")
console = Console()


@app.callback(invoke_without_command=True)
def discover(
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
) -> None:
    """Convert ranked discoveries into Threads drafts via Claude."""
    from orbit.commands.draft import _run_draft_generation  # lazy: avoids circular import on cold load

    db = DB()
    indices = _parse_int_list(picks)
    if not indices:
        console.print(f"\n[red]Could not parse '{picks}'.[/red] Use e.g. [cyan]1,3,5[/cyan].\n")
        raise typer.Exit(1)

    # Pull the most recently displayed top picks. We persist them with status='new'
    # and ordered by created_at DESC, then by score DESC within the latest batch.
    rows = list(db.conn.query(
        "SELECT id, tweet_id, url, text, author, media_url, media_type "
        "FROM discoveries WHERE status = 'new' ORDER BY score DESC LIMIT 50"
    ))
    if not rows:
        console.print("\n[yellow]No fresh discoveries.[/yellow] "
                      "Run [cyan]orbit discover[/cyan] first.\n")
        raise typer.Exit(1)

    chosen = [rows[i - 1] for i in indices if 1 <= i <= len(rows)]
    if not chosen:
        console.print(f"\n[red]None of {picks} are in range 1..{len(rows)}.[/red]\n")
        raise typer.Exit(1)

    # Reshape into the bookmark-like dicts that draft.py knows how to consume
    fake_bookmarks = [{
        "text": r["text"],
        "author": r["author"],
        "url": r["url"],
        "media_url": r.get("media_url"),
        "media_type": r.get("media_type"),
    } for r in chosen]

    console.print(f"\n[dim]Generating Threads drafts from {len(chosen)} discoveries...[/dim]\n")
    _run_draft_generation(fake_bookmarks)

    # Mark the chosen ones as drafted so they don't re-appear
    for r in chosen:
        db.conn["discoveries"].update(r["id"], {"status": "drafted"})


# --- helpers ---


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
