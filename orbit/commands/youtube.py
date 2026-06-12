"""orbit youtube — Jeff-Sue-style YouTube production checklist.

Each new checklist is seeded from orbit.youtube_checklist_template.TEMPLATE so
you start with a vetted Pre-prod → Scripting → Filming → Post-prod skeleton,
then customize per video.
"""
from __future__ import annotations
from datetime import datetime, timezone

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from orbit.db import DB
from orbit.youtube_checklist_template import TEMPLATE

app = typer.Typer(help="YouTube video production checklists")
console = Console()


@app.command("new")
def new(
    title: str = typer.Argument(..., help="Working title for this video"),
) -> None:
    """Create a new checklist seeded from the template."""
    db = DB()
    now = datetime.now(timezone.utc).isoformat()
    checklist_id = db.conn["youtube_checklists"].insert({
        "title": title,
        "status": "in_progress",
        "created_at": now,
    }).last_pk

    for i, item in enumerate(TEMPLATE):
        db.conn["youtube_checklist_items"].insert({
            "checklist_id": checklist_id,
            "phase": item.phase,
            "order_idx": i,
            "label": item.label,
            "detail": item.detail,
            "blocks_next": 1 if item.blocks_next else 0,
        })

    console.print(f"\n[green]✓[/green] Created checklist [bold]{checklist_id}[/bold]: {title}")
    console.print(f"  [dim]{len(TEMPLATE)} items across "
                  f"{len({i.phase for i in TEMPLATE})} phases.[/dim]")
    console.print(f"  [dim]View with[/dim] [cyan]orbit youtube show {checklist_id}[/cyan]\n")


@app.command("list")
def list_checklists(
    status: str = typer.Option(None, "--status", "-s", help="Filter (in_progress / shipped / abandoned)"),
) -> None:
    """List checklists."""
    db = DB()
    sql = "SELECT id, title, status, created_at FROM youtube_checklists"
    args: list = []
    if status:
        sql += " WHERE status = ?"
        args.append(status)
    sql += " ORDER BY id DESC LIMIT 30"
    rows = list(db.conn.query(sql, args))

    if not rows:
        console.print("\n[yellow]No checklists.[/yellow] "
                      "Start one with [cyan]orbit youtube new \"My video title\"[/cyan]\n")
        return

    # Pull completion stats per checklist
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("ID", justify="right", style="bold")
    table.add_column("Status")
    table.add_column("Progress")
    table.add_column("Title", no_wrap=False, max_width=60)
    table.add_column("Created")

    for r in rows:
        stats = list(db.conn.query(
            "SELECT COUNT(*) AS total, "
            "       SUM(CASE WHEN completed_at IS NOT NULL THEN 1 ELSE 0 END) AS done "
            "FROM youtube_checklist_items WHERE checklist_id = ?",
            [r["id"]],
        ))[0]
        done, total = stats["done"] or 0, stats["total"] or 0
        progress = f"{done}/{total}"
        table.add_row(
            str(r["id"]),
            _color_status(r["status"]),
            progress,
            r["title"],
            (r["created_at"] or "")[:10],
        )
    console.print()
    console.print(table)
    console.print()


@app.command("show")
def show(
    checklist_id: int = typer.Argument(...),
    full: bool = typer.Option(False, "--full", "-f", help="Show details for every item, not just the next one"),
) -> None:
    """Show a checklist. By default, focuses on the next unchecked item (Jeff's
    'I can't proceed until this is confirmed' discipline). --full shows everything."""
    db = DB()
    cl = _get_checklist(db, checklist_id)
    items = list(db.conn.query(
        "SELECT id, phase, order_idx, label, detail, blocks_next, completed_at, notes "
        "FROM youtube_checklist_items WHERE checklist_id = ? ORDER BY order_idx",
        [checklist_id],
    ))

    console.print(f"\n[bold]{cl['title']}[/bold]  [dim]({_color_status(cl['status'])})[/dim]")
    done = sum(1 for i in items if i["completed_at"])
    console.print(f"  [dim]{done}/{len(items)} complete[/dim]\n")

    if not full:
        # Find the next unchecked item; flag if a blocker upstream is open
        next_idx = next((i for i, it in enumerate(items) if not it["completed_at"]), None)
        if next_idx is None:
            console.print("[green]✓ All items complete![/green] "
                          f"Mark this checklist shipped with [cyan]orbit youtube ship {checklist_id}[/cyan]\n")
            return

        # Show all phases with check states + the next item highlighted
        last_phase = None
        for i, it in enumerate(items):
            if it["phase"] != last_phase:
                last_phase = it["phase"]
                console.print(f"\n[bold magenta]── {it['phase']} ──[/bold magenta]")
            check = "[green]✓[/green]" if it["completed_at"] else (
                "[cyan]▶[/cyan]" if i == next_idx else "[dim]·[/dim]"
            )
            style = "" if not it["completed_at"] else "dim strike"
            label_md = f"[{style}]{it['label']}[/{style}]" if style else it["label"]
            blocker = "  [yellow](blocks downstream)[/yellow]" if it["blocks_next"] and not it["completed_at"] else ""
            console.print(f"  {check} [bold]#{it['id']}[/bold]  {label_md}{blocker}")

        # Detail for the next item only
        nxt = items[next_idx]
        console.print()
        console.print(Panel(
            nxt["detail"] or "[dim](no extra detail)[/dim]",
            title=f"[bold cyan]Next: #{nxt['id']} — {nxt['label']}[/bold cyan]",
            border_style="cyan",
        ))
        console.print(f"\n[dim]Mark done:[/dim] [cyan]orbit youtube check {nxt['id']}[/cyan]")
        console.print(f"[dim]Add a note:[/dim] [cyan]orbit youtube note {nxt['id']} \"...\"[/cyan]\n")
    else:
        last_phase = None
        for it in items:
            if it["phase"] != last_phase:
                last_phase = it["phase"]
                console.print(f"\n[bold magenta]── {it['phase']} ──[/bold magenta]")
            check = "[green]✓[/green]" if it["completed_at"] else "[dim]·[/dim]"
            console.print(f"  {check} [bold]#{it['id']}[/bold]  {it['label']}")
            if it["detail"]:
                for line in it["detail"].splitlines():
                    console.print(f"        [dim]{line}[/dim]")
            if it["notes"]:
                console.print(f"        [yellow]NOTE: {it['notes']}[/yellow]")
        console.print()


@app.command("check")
def check(item_id: int = typer.Argument(..., help="Item id (from `orbit youtube show`)")) -> None:
    """Mark an item complete."""
    db = DB()
    rows = list(db.conn.query(
        "SELECT id, checklist_id, label, completed_at FROM youtube_checklist_items WHERE id = ?",
        [item_id],
    ))
    if not rows:
        console.print(f"\n[red]No item #{item_id}.[/red]\n")
        raise typer.Exit(1)
    r = rows[0]
    if r["completed_at"]:
        console.print(f"\n[yellow]Item #{item_id} already done.[/yellow]\n")
        return

    # Enforce blocks_next: can't check an item if an earlier blocker is open
    blockers = list(db.conn.query(
        "SELECT id, label FROM youtube_checklist_items "
        "WHERE checklist_id = ? AND order_idx < ("
        "  SELECT order_idx FROM youtube_checklist_items WHERE id = ?"
        ") AND blocks_next = 1 AND completed_at IS NULL",
        [r["checklist_id"], item_id],
    ))
    if blockers:
        console.print(f"\n[red]✗ Can't check #{item_id} yet — a blocker is open:[/red]")
        for b in blockers:
            console.print(f"  [cyan]#{b['id']}[/cyan]  {b['label']}")
        console.print(f"\n[dim]Finish the blocker first, then check #{item_id}.[/dim]\n")
        raise typer.Exit(1)

    db.conn["youtube_checklist_items"].update(item_id, {
        "completed_at": datetime.now(timezone.utc).isoformat(),
    })
    console.print(f"\n[green]✓ #{item_id}[/green]  {r['label']}\n")


@app.command("uncheck")
def uncheck(item_id: int = typer.Argument(...)) -> None:
    """Unmark an item (in case you checked it too early)."""
    db = DB()
    rows = list(db.conn.query("SELECT id, label FROM youtube_checklist_items WHERE id = ?", [item_id]))
    if not rows:
        console.print(f"\n[red]No item #{item_id}.[/red]\n")
        raise typer.Exit(1)
    db.conn["youtube_checklist_items"].update(item_id, {"completed_at": None})
    console.print(f"\n[yellow]↺ #{item_id}[/yellow]  {rows[0]['label']}\n")


@app.command("note")
def note(
    item_id: int = typer.Argument(...),
    text: str = typer.Argument(..., help="Note text"),
) -> None:
    """Attach a note to a checklist item (e.g. 'thumbnail v2 = blue bg + surprised face')."""
    db = DB()
    rows = list(db.conn.query("SELECT id, label, notes FROM youtube_checklist_items WHERE id = ?", [item_id]))
    if not rows:
        console.print(f"\n[red]No item #{item_id}.[/red]\n")
        raise typer.Exit(1)
    existing = rows[0]["notes"] or ""
    new_notes = f"{existing}\n{text}".strip() if existing else text
    db.conn["youtube_checklist_items"].update(item_id, {"notes": new_notes})
    console.print(f"\n[green]✓ Note added to #{item_id}.[/green]\n")


@app.command("ship")
def ship(
    checklist_id: int = typer.Argument(...),
    video_id: str = typer.Option(None, "--video", "-v", help="YouTube video ID once live"),
) -> None:
    """Mark a checklist shipped (with optional published video id)."""
    db = DB()
    cl = _get_checklist(db, checklist_id)
    updates = {"status": "shipped", "shipped_at": datetime.now(timezone.utc).isoformat()}
    if video_id:
        updates["video_id"] = video_id
    db.conn["youtube_checklists"].update(checklist_id, updates)
    console.print(f"\n[green]🎬 Shipped:[/green] {cl['title']}")
    if video_id:
        console.print(f"  [dim]https://www.youtube.com/watch?v={video_id}[/dim]")
    console.print()


# --- helpers ---


def _get_checklist(db: DB, checklist_id: int) -> dict:
    rows = list(db.conn.query("SELECT * FROM youtube_checklists WHERE id = ?", [checklist_id]))
    if not rows:
        console.print(f"\n[red]No checklist #{checklist_id}.[/red]\n")
        raise typer.Exit(1)
    return rows[0]


def _color_status(status: str | None) -> str:
    palette = {
        "in_progress": "[cyan]in_progress[/cyan]",
        "shipped": "[green]shipped[/green]",
        "abandoned": "[dim]abandoned[/dim]",
    }
    return palette.get(status or "", status or "—")
