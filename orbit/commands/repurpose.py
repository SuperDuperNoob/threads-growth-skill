"""orbit repurpose — turn your YouTube videos into Threads drafts.

Pipeline:
1. List your YouTube videos by views (so highest-performing first).
2. User picks one. Fetch transcript (cached on disk).
3. Ask Claude to extract 3-5 "tweet-able moments" from the transcript.
4. For each moment, run the existing draft-generation pipeline to produce
   3 Threads drafts in your voice.
"""
from __future__ import annotations
import os
import re
from datetime import datetime, timezone

import anthropic
import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from orbit.config import Config
from orbit.db import DB
from orbit.platforms.youtube_transcript import (
    TranscriptUnavailable,
    YouTubeTranscriptClient,
)

app = typer.Typer(help="Turn your YouTube videos into Threads drafts")
console = Console()


@app.callback(invoke_without_command=True)
def repurpose(
    video_id: str = typer.Option(
        None, "--video", "-v",
        help="Skip the picker; repurpose this exact video ID",
    ),
    limit: int = typer.Option(
        15, "--limit", "-n", help="How many top videos to list",
    ),
    refresh: bool = typer.Option(
        False, "--refresh", "-r", help="Re-fetch transcript even if cached",
    ),
) -> None:
    """Pick a YouTube video, extract tweet-able moments, generate drafts."""
    cfg = Config()
    db = DB()

    api_key = os.environ.get("ANTHROPIC_API_KEY") or cfg.get("anthropic.api_key")
    if not api_key:
        console.print("\n[red]✗ ANTHROPIC_API_KEY not set.[/red] "
                      "Run: [cyan]orbit setup --platform anthropic[/cyan]\n")
        raise typer.Exit(1)

    chosen_id, chosen_title = _resolve_choice(db, video_id, limit)
    if not chosen_id:
        return

    transcripts = YouTubeTranscriptClient()
    console.print(f"\n[dim]Fetching transcript for {chosen_id}...[/dim]")
    try:
        transcript = transcripts.fetch(chosen_id, force=refresh)
    except TranscriptUnavailable as e:
        console.print(f"\n[red]✗ {e}[/red]\n")
        raise typer.Exit(1)
    console.print(f"  [green]✓[/green] {transcript.snippet_count} snippets, "
                  f"{len(transcript.text):,} chars ({transcript.language})")

    ai = anthropic.Anthropic(api_key=api_key)
    moments = _extract_moments(ai, chosen_title, transcript.text)
    if not moments:
        console.print("\n[red]✗ Claude returned no moments. Try --refresh or a different video.[/red]\n")
        raise typer.Exit(1)

    console.print(f"\n[bold]{len(moments)} tweet-able moments from this video:[/bold]\n")
    for i, m in enumerate(moments, 1):
        console.print(Panel(m, title=f"[bold cyan]Moment {i}[/bold cyan]", border_style="cyan"))
        console.print()

    raw = Prompt.ask(
        "Pick which moments to turn into drafts (e.g. [cyan]1[/cyan] or [cyan]1,3[/cyan] — Enter to skip)",
        default="",
    )
    indices = _parse_picks(raw, len(moments))
    if not indices:
        console.print("\n[dim]No moments picked. Run again to try different ones.[/dim]\n")
        return

    # Reshape picked moments into "bookmark-like" sources for the draft pipeline.
    # source_url points to the YouTube video so the link is preserved.
    video_url = f"https://www.youtube.com/watch?v={chosen_id}"
    fake_sources = [{
        "text": moments[i],
        "author": "@you",
        "url": video_url,
    } for i in indices]

    from orbit.commands.draft import _run_draft_generation
    _run_draft_generation(fake_sources)


# --- helpers ---


def _resolve_choice(db: DB, video_id: str | None, limit: int) -> tuple[str | None, str]:
    """If --video provided, validate it. Otherwise show top videos and let user pick."""
    if video_id:
        rows = list(db.conn.query(
            "SELECT d.content AS title, p.external_id "
            "FROM posts p JOIN drafts d ON d.id = p.draft_id "
            "WHERE p.platform='youtube' AND p.external_id = ?",
            [video_id],
        ))
        if not rows:
            console.print(f"\n[yellow]No YouTube post in DB with id {video_id}.[/yellow] "
                          "Will fetch transcript anyway.\n")
            return video_id, video_id
        return video_id, rows[0]["title"]

    rows = list(db.conn.query("""
        SELECT d.content AS title, p.external_id,
               MAX(m.views) AS views, MAX(m.likes) AS likes, MAX(m.comments) AS comments
        FROM posts p
        JOIN drafts d ON d.id = p.draft_id
        JOIN metrics m ON m.post_id = p.id
        WHERE p.platform = 'youtube'
        GROUP BY p.external_id
        ORDER BY views DESC
        LIMIT ?
    """, [limit]))

    if not rows:
        console.print("\n[yellow]No YouTube data.[/yellow] "
                      "Run [cyan]orbit sync --platform youtube[/cyan] first.\n")
        return None, ""

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("#", justify="right", style="bold")
    table.add_column("Title", no_wrap=False, max_width=55)
    table.add_column("Views", justify="right")
    table.add_column("Likes", justify="right")
    table.add_column("ID")
    for i, r in enumerate(rows, 1):
        table.add_row(
            str(i),
            (r["title"] or "")[:55],
            f"{(r['views'] or 0):,}",
            f"{(r['likes'] or 0):,}",
            r["external_id"] or "",
        )
    console.print()
    console.print(table)
    console.print()

    raw = Prompt.ask("Pick a video by number (Enter to cancel)", default="").strip()
    if not raw or not raw.isdigit():
        return None, ""
    idx = int(raw) - 1
    if not (0 <= idx < len(rows)):
        return None, ""
    return rows[idx]["external_id"], rows[idx]["title"] or ""


def _extract_moments(ai: anthropic.Anthropic, title: str, transcript: str) -> list[str]:
    """Ask Claude to pull 3-5 tweet-able moments out of the transcript."""
    # Long transcripts: keep things safe. Claude can handle 25k chars but the prompt
    # gets noisy. Truncate to ~12k chars (still ~2k snippets of dialog).
    excerpt = transcript[:12_000]
    truncated = len(transcript) > 12_000

    prompt = f"""You are reading a transcript of a YouTube video by Keith. Your job: extract 3-5 distinct "tweet-able moments" — specific insights, results, surprises, or contrarian takes that could each become a standalone social media post.

VIDEO TITLE: {title}

TRANSCRIPT{' (truncated, first 12k chars)' if truncated else ''}:
\"\"\"
{excerpt}
\"\"\"

REQUIREMENTS for each moment:
- Self-contained: a reader should understand it without watching the video
- SPECIFIC: include exact numbers, tool names, costs, durations he mentioned
- ORIGINAL: based on Keith's lived experience or experiment in the video, not generic AI commentary
- One paragraph (2-5 sentences), in English (a draft writer will translate later)
- Different from the others — don't repeat the same point with different words

OUTPUT FORMAT: Number each moment [1], [2], [3]... Just the moments, no headers or commentary. Stop after the last numbered moment — no closing remarks, no "hope this helps", nothing after [N]."""
    msg = ai.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text
    return _parse_moments(raw)


def _parse_moments(text: str) -> list[str]:
    """Parse `[1] ... [2] ... [3] ...` into a list of moments."""
    parts = re.split(r"\[(\d+)\]", text)
    out: list[str] = []
    for i in range(1, len(parts), 2):
        content = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if content:
            out.append(content)
    return out


def _parse_picks(raw: str, n: int) -> list[int]:
    """'1,3' → [0, 2]. Drops invalid/out-of-range tokens."""
    seen: set[int] = set()
    out: list[int] = []
    for tok in re.split(r"[,\s]+", raw.strip()):
        if not tok or not tok.isdigit():
            continue
        idx = int(tok) - 1
        if 0 <= idx < n and idx not in seen:
            seen.add(idx)
            out.append(idx)
    return out
