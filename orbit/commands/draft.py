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
from orbit.platforms.twitter import BookmarkCache, TwitterClient

app = typer.Typer(help="Generate Threads drafts from your X bookmarks")
console = Console()

_CACHE_PATH = Path.home() / ".orbit" / "bookmarks_cache.json"


@app.callback(invoke_without_command=True)
def draft(
    force_refresh: bool = typer.Option(False, "--refresh", "-r", help="Force re-fetch bookmarks"),
) -> None:
    cfg = Config()
    db = DB()

    cookies_path = cfg.get("twitter.cookies_path")
    if not cookies_path:
        console.print("\n[red]✗ Twitter not configured.[/red] Run: [cyan]orbit setup --platform twitter[/cyan]\n")
        raise typer.Exit(1)

    api_key = os.environ.get("ANTHROPIC_API_KEY") or cfg.get("anthropic.api_key")
    if not api_key:
        console.print("\n[red]✗ ANTHROPIC_API_KEY not set.[/red]")
        console.print("  Set it with: [cyan]export ANTHROPIC_API_KEY=sk-ant-...[/cyan]")
        console.print("  Or run: [cyan]orbit setup --platform anthropic[/cyan]\n")
        raise typer.Exit(1)

    cache = BookmarkCache(_CACHE_PATH)
    bookmarks = None if force_refresh else cache.load()

    if bookmarks is None:
        console.print("\n[dim]Fetching X bookmarks...[/dim]")
        try:
            client = TwitterClient(cookies_path=cookies_path)
            bookmarks = client.get_bookmarks(limit=50)
            cache.save(bookmarks)
            console.print(f"  [green]✓[/green] Fetched {len(bookmarks)} bookmarks\n")
        except FileNotFoundError:
            console.print("\n[red]✗ Cookie file not found.[/red] Re-run: [cyan]orbit setup --platform twitter[/cyan]\n")
            raise typer.Exit(1)
        except Exception as e:
            console.print(f"\n[red]✗ Failed to fetch bookmarks: {e}[/red]")
            console.print("  Your session may have expired. Re-run: [cyan]orbit setup --platform twitter[/cyan]\n")
            raise typer.Exit(1)
    else:
        console.print(f"\n[dim]Using cached bookmarks ({len(bookmarks)} items)[/dim]\n")

    if not bookmarks:
        console.print("[yellow]No bookmarks found.[/yellow] Make sure you have bookmarks on X.\n")
        raise typer.Exit(1)

    rows = db.conn.execute("""
        SELECT d.content, m.views, m.likes
        FROM posts p
        JOIN drafts d ON d.id = p.draft_id
        JOIN metrics m ON m.post_id = p.id
        WHERE p.platform = 'threads'
        ORDER BY m.views DESC
        LIMIT 10
    """).fetchall()

    if not rows:
        console.print("[yellow]No Threads data yet.[/yellow] Run [cyan]orbit sync --platform threads[/cyan] first.\n")
        raise typer.Exit(1)

    top_posts = [{"content": r[0], "views": r[1], "likes": r[2]} for r in rows]
    top_patterns = extract_top_patterns(top_posts, top_n=5)

    console.print("[dim]Generating drafts with Claude...[/dim]\n")
    prompt = build_pattern_prompt(top_patterns, bookmarks)

    ai = anthropic.Anthropic(api_key=api_key)
    message = ai.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text

    drafts = _parse_drafts(raw)

    if not drafts:
        console.print("[red]✗ Could not parse drafts from Claude response.[/red]")
        console.print(raw)
        raise typer.Exit(1)

    console.print()
    for i, d in enumerate(drafts, 1):
        console.print(Panel(d, title=f"[bold cyan]Draft {i}[/bold cyan]", border_style="cyan"))
        console.print()

    choice = Prompt.ask(
        "Save a draft? Enter number or press Enter to discard all",
        default="",
    )

    if choice.strip() in ("1", "2", "3"):
        idx = int(choice.strip()) - 1
        if idx < len(drafts):
            now = datetime.now(timezone.utc).isoformat()
            idea_id = db.conn["ideas"].insert({
                "title": drafts[idx][:80],
                "source": "draft",
                "status": "draft",
                "created_at": now,
            }).last_pk
            db.conn["drafts"].insert({
                "idea_id": idea_id,
                "platform": "threads",
                "content": drafts[idx],
                "status": "draft",
                "created_at": now,
            })
            console.print(f"\n[green]✓ Draft {choice} saved.[/green]\n")
        else:
            console.print("[yellow]Invalid choice.[/yellow]\n")
    else:
        console.print("\n[dim]Discarded. Run again for fresh drafts.[/dim]\n")


def _parse_drafts(text: str) -> list[str]:
    parts = re.split(r"\[([123])\]", text)
    drafts = []
    for i in range(1, len(parts), 2):
        content = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if content:
            drafts.append(content)
    return drafts
