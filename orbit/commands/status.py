from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from orbit.config import Config
from orbit.db import DB
from orbit.patterns import PatternStore

app = typer.Typer(help="Show configuration and sync status")
console = Console()

PLATFORMS = ["linkedin", "youtube", "threads", "facebook", "substack"]

_CREDENTIAL_KEYS: dict[str, list[str]] = {
    "linkedin": ["linkedin.access_token", "linkedin.author_urn"],
    "youtube": ["youtube.access_token", "youtube.channel_id"],
    "threads": ["threads.access_token"],
    "facebook": ["facebook.access_token"],
    "substack": ["substack.publication_url"],
}


@app.callback(invoke_without_command=True)
def status() -> None:
    cfg = Config()
    db = DB()
    ps = PatternStore()

    console.print("\n[bold]Orbit Status[/bold]\n")

    # --- Platforms table ---
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Platform", style="bold")
    table.add_column("Configured", justify="center")
    table.add_column("Posts in DB", justify="right")
    table.add_column("Last Synced", justify="right")
    table.add_column("Pattern Sample", justify="right")

    for platform in PLATFORMS:
        keys = _CREDENTIAL_KEYS.get(platform, [])
        configured = all(cfg.get(k) for k in keys)
        configured_str = "[green]✓[/green]" if configured else "[red]✗[/red]"

        post_count = db.conn.execute(
            "SELECT COUNT(*) FROM posts WHERE platform = ?", [platform]
        ).fetchone()[0]

        last_synced = db.conn.execute(
            "SELECT MAX(pulled_at) FROM metrics WHERE platform = ?", [platform]
        ).fetchone()[0]
        last_synced_str = last_synced[:10] if last_synced else "never"

        pattern = ps.load(platform)
        sample = pattern.get("sample_size", 0)
        sample_str = str(sample) if sample else "[dim]0[/dim]"

        table.add_row(
            platform.title(),
            configured_str,
            str(post_count) if post_count else "[dim]0[/dim]",
            last_synced_str,
            sample_str,
        )

    console.print(table)

    # --- Quick tips ---
    unconfigured = [
        p for p in PLATFORMS
        if not all(cfg.get(k) for k in _CREDENTIAL_KEYS.get(p, []))
    ]
    unsynced = [
        p for p in ["linkedin", "youtube"]
        if db.conn.execute(
            "SELECT COUNT(*) FROM posts WHERE platform = ?", [p]
        ).fetchone()[0] == 0
    ]

    if unconfigured:
        console.print(
            f"\n[yellow]Not configured:[/yellow] {', '.join(p.title() for p in unconfigured)}"
            f"\n  Run [cyan]orbit setup[/cyan] to connect them."
        )
    if unsynced:
        configured_unsynced = [p for p in unsynced if p not in unconfigured]
        if configured_unsynced:
            console.print(
                f"\n[yellow]Configured but never synced:[/yellow] {', '.join(p.title() for p in configured_unsynced)}"
                f"\n  Run [cyan]orbit sync[/cyan] to pull your post history."
            )
    console.print()
