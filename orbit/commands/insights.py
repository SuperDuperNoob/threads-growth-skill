from __future__ import annotations
from typing import Any

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich.text import Text
from rich import box

from orbit.db import DB

app = typer.Typer(help="Analyze your content performance")
console = Console()


@app.callback(invoke_without_command=True)
def insights(
    platform: str = typer.Option("youtube", "--platform", "-p", help="Platform to analyze"),
    limit: int = typer.Option(10, "--limit", "-n", help="Number of top posts to show"),
) -> None:
    db = DB()

    rows = db.conn.execute("""
        SELECT d.content AS title, p.published_at, p.external_id,
               m.views, m.likes, m.comments, d.source_links
        FROM posts p
        JOIN drafts d ON d.id = p.draft_id
        JOIN metrics m ON m.post_id = p.id
        WHERE p.platform = ?
        ORDER BY m.pulled_at DESC
    """, [platform]).fetchall()

    if not rows:
        console.print(f"\n[yellow]No data for {platform}. Run [cyan]orbit sync --platform {platform}[/cyan] first.[/yellow]\n")
        raise typer.Exit()

    # Deduplicate by external_id (keep latest metrics pull)
    seen: set[str] = set()
    data: list[dict[str, Any]] = []
    for r in rows:
        if r[2] not in seen:
            seen.add(r[2])
            views = r[3] or 0
            likes = r[4] or 0
            comments = r[5] or 0
            data.append({
                "title": r[0],
                "published_at": r[1],
                "external_id": r[2],
                "views": views,
                "likes": likes,
                "comments": comments,
                "like_rate": round(likes / views * 100, 2) if views else 0.0,
                "comment_rate": round(comments / views * 100, 3) if views else 0.0,
                "engagement": round((likes + comments) / views * 100, 2) if views else 0.0,
                "source_links": r[6],
            })

    total_views = sum(d["views"] for d in data)
    total_likes = sum(d["likes"] for d in data)
    total_comments = sum(d["comments"] for d in data)
    avg_views = total_views // len(data) if data else 0
    avg_like_rate = round(total_likes / total_views * 100, 2) if total_views else 0
    avg_comment_rate = round(total_comments / total_views * 100, 3) if total_views else 0

    console.print()

    # --- Summary panels ---
    summary_items = [
        Panel(
            f"[bold white]{total_views:,}[/bold white]\n[dim]total views[/dim]",
            border_style="cyan", expand=True,
        ),
        Panel(
            f"[bold white]{len(data)}[/bold white]\n[dim]videos[/dim]",
            border_style="cyan", expand=True,
        ),
        Panel(
            f"[bold white]{avg_views:,}[/bold white]\n[dim]avg views[/dim]",
            border_style="cyan", expand=True,
        ),
        Panel(
            f"[bold white]{avg_like_rate}%[/bold white]\n[dim]avg like rate[/dim]",
            border_style="cyan", expand=True,
        ),
        Panel(
            f"[bold white]{avg_comment_rate}%[/bold white]\n[dim]avg comment rate[/dim]",
            border_style="cyan", expand=True,
        ),
    ]
    console.print(Columns(summary_items, equal=True, expand=True))
    console.print()

    # --- Top by views ---
    top_views = sorted(data, key=lambda d: d["views"], reverse=True)[:limit]
    view_table = Table(
        title=f"Top {limit} by Views",
        box=box.SIMPLE_HEAD,
        header_style="bold cyan",
        show_edge=False,
    )
    view_table.add_column("Title", no_wrap=False, max_width=55)
    view_table.add_column("Views", justify="right")
    view_table.add_column("Likes", justify="right")
    view_table.add_column("Comments", justify="right")
    view_table.add_column("Like %", justify="right")

    for d in top_views:
        like_style = "green" if d["like_rate"] >= avg_like_rate else "dim"
        view_table.add_row(
            d["title"][:55],
            f"{d['views']:,}",
            f"{d['likes']:,}",
            f"{d['comments']:,}",
            f"[{like_style}]{d['like_rate']}%[/{like_style}]",
        )
    console.print(view_table)

    # --- Top by engagement ---
    top_eng = sorted(data, key=lambda d: d["like_rate"], reverse=True)[:limit]
    eng_table = Table(
        title=f"Top {limit} by Like Rate",
        box=box.SIMPLE_HEAD,
        header_style="bold magenta",
        show_edge=False,
    )
    eng_table.add_column("Title", no_wrap=False, max_width=55)
    eng_table.add_column("Like %", justify="right")
    eng_table.add_column("Views", justify="right")
    eng_table.add_column("Likes", justify="right")

    for d in top_eng:
        eng_table.add_row(
            d["title"][:55],
            f"[bold magenta]{d['like_rate']}%[/bold magenta]",
            f"{d['views']:,}",
            f"{d['likes']:,}",
        )
    console.print(eng_table)

    # --- Signal: high views AND high engagement ---
    both = [d for d in data if d["views"] >= avg_views and d["like_rate"] >= avg_like_rate]
    if both:
        console.print(
            Panel(
                "\n".join(f"  [bold green]✦[/bold green] {d['title'][:70]}" for d in both),
                title="[bold]Make more of this[/bold]  (above avg views + above avg like rate)",
                border_style="green",
            )
        )

    console.print()
