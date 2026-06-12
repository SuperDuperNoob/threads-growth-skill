from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from orbit.config import Config
from orbit.db import DB
from orbit.platforms import postiz
from orbit.platforms.threads import ThreadsClient

app = typer.Typer(help="Browse and manage saved drafts")
console = Console()


@app.command("list")
def list_drafts(
    platform: str = typer.Option("threads", "--platform", "-p", help="Filter by platform"),
    status: str = typer.Option(None, "--status", "-s", help="Filter by status (draft/scheduled/published)"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max rows to show"),
) -> None:
    """List saved drafts."""
    db = DB()
    where = ["platform = ?"]
    args: list = [platform]
    if status:
        where.append("status = ?")
        args.append(status)
    rows = list(db.conn.query(
        f"SELECT id, status, publish_at, created_at, content FROM drafts "
        f"WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT ?",
        [*args, limit],
    ))

    if not rows:
        console.print(f"\n[yellow]No {platform} drafts found.[/yellow] "
                      f"Run [cyan]orbit draft[/cyan] to make some.\n")
        return

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("ID", style="bold", justify="right")
    table.add_column("Status")
    table.add_column("Scheduled")
    table.add_column("Created")
    table.add_column("Preview")
    for r in rows:
        preview = (r["content"] or "").replace("\n", " ")
        if len(preview) > 60:
            preview = preview[:57] + "…"
        table.add_row(
            str(r["id"]),
            _color_status(r["status"]),
            r["publish_at"] or "—",
            (r["created_at"] or "")[:19].replace("T", " "),
            preview,
        )
    console.print()
    console.print(table)
    console.print(f"\n[dim]Show full text:[/dim] [cyan]orbit drafts show <id>[/cyan]\n")


@app.command("show")
def show(draft_id: int = typer.Argument(..., help="Draft id from `orbit drafts list`")) -> None:
    """Show one draft in full."""
    db = DB()
    rows = list(db.conn.query(
        "SELECT id, platform, status, publish_at, created_at, content FROM drafts WHERE id = ?",
        [draft_id],
    ))
    if not rows:
        console.print(f"\n[red]No draft with id {draft_id}.[/red]\n")
        raise typer.Exit(1)
    r = rows[0]
    console.print()
    console.print(Panel(
        r["content"],
        title=f"[bold cyan]Draft {r['id']}[/bold cyan]  ·  {r['platform']}  ·  {_color_status(r['status'])}",
        border_style="cyan",
    ))
    if r.get("publish_at"):
        console.print(f"  [dim]Scheduled for[/dim] {r['publish_at']}")
    console.print()


@app.command("publish")
def publish(draft_id: int = typer.Argument(..., help="Draft id to publish to Threads")) -> None:
    """Publish a saved draft to Threads now."""
    cfg = Config()
    db = DB()
    rows = list(db.conn.query("SELECT id, platform, status, content FROM drafts WHERE id = ?", [draft_id]))
    if not rows:
        console.print(f"\n[red]No draft with id {draft_id}.[/red]\n")
        raise typer.Exit(1)
    r = rows[0]
    if r["platform"] != "threads":
        console.print(f"\n[red]Draft {draft_id} is for {r['platform']}, not threads.[/red]\n")
        raise typer.Exit(1)
    if r["status"] == "published":
        console.print(f"\n[yellow]Draft {draft_id} is already published.[/yellow]\n")
        raise typer.Exit(1)

    token = cfg.get("threads.access_token")
    user_id = cfg.get("threads.user_id")
    if not token or not user_id:
        console.print("\n[red]✗ Threads not configured.[/red] Run: [cyan]orbit setup --platform threads[/cyan]\n")
        raise typer.Exit(1)

    client = ThreadsClient(access_token=token, user_id=user_id)
    try:
        thread_id = client.create_post(r["content"])
    except Exception as e:
        console.print(f"\n[red]✗ Publish failed: {e}[/red]\n")
        raise typer.Exit(1)

    now = datetime.now(timezone.utc).isoformat()
    db.conn["drafts"].update(draft_id, {"status": "published"})
    db.conn["posts"].insert({
        "draft_id": draft_id,
        "platform": "threads",
        "external_id": thread_id,
        "published_at": now,
    })
    console.print(f"\n[green]✓ Posted thread {thread_id}.[/green]\n")


@app.command("handoff")
def handoff(
    draft_id: int = typer.Argument(..., help="Draft id to hand off to Postiz"),
    threads_only: bool = typer.Option(False, "--threads-only", help="Skip Facebook, post to Threads only"),
    as_draft: bool = typer.Option(False, "--draft", help="Create a Postiz draft instead of scheduling"),
    force: bool = typer.Option(
        False,
        "--force",
        help="Re-handoff an already-handed-off draft (delete the old Postiz posts manually first).",
    ),
) -> None:
    """Hand a scheduled draft off to Postiz (which handles publishing)."""
    result = do_handoff(draft_id, threads_only=threads_only, as_draft=as_draft, force=force)
    if not result.ok:
        console.print(f"\n[red]✗ {result.message}[/red]\n")
        raise typer.Exit(1)
    console.print(f"\n[green]✓ {result.message}[/green]\n")


@app.command("comment")
def set_comment(
    draft_id: int = typer.Argument(..., help="Draft id"),
    url: str = typer.Argument(..., help="URL to attach as a threaded comment (e.g. github.com/org/repo)"),
) -> None:
    """Set a comment URL on a draft for the next handoff.

    Useful when the source X tweet mentioned a project but didn't link it (so
    source_links is empty). After running this, re-handoff the draft and the
    URL goes as a threaded reply on the Postiz post.
    """
    import json as _json
    db = DB()
    rows = list(db.conn.query(
        "SELECT id, status, source_links FROM drafts WHERE id = ?",
        [draft_id],
    ))
    if not rows:
        console.print(f"\n[red]No draft with id {draft_id}.[/red]\n")
        raise typer.Exit(1)
    r = rows[0]
    # Merge with any existing source_links so we don't clobber legit data
    existing: list = []
    if r["source_links"]:
        try:
            existing = _json.loads(r["source_links"]) or []
        except (ValueError, TypeError):
            existing = []
    if url not in existing:
        existing.append(url)
    db.conn["drafts"].update(draft_id, {"source_links": _json.dumps(existing)})
    console.print(f"\n[green]✓ Attached[/green] [cyan]{url}[/cyan] [green]as a comment on draft {draft_id}.[/green]")
    if r["status"] == "handed_off_to_postiz":
        console.print(
            "[yellow]Note:[/yellow] this draft is already on Postiz. To apply the new comment, "
            f"you'll need to delete the Postiz posts and re-run [cyan]orbit drafts handoff {draft_id}[/cyan]."
        )
    else:
        console.print(
            f"[dim]Run[/dim] [cyan]orbit drafts handoff {draft_id}[/cyan] [dim]to push to Postiz.[/dim]"
        )
    console.print()


@dataclass
class HandoffResult:
    ok: bool
    message: str
    postiz_id: str | None = None


def _pick_comment_link(source_links_json: str | None) -> str | None:
    """Pick the best URL from a draft's source_links for use as a threaded comment.

    Preference order: github.com > other forge (gitlab/bitbucket) > anything else.
    Returns "GitHub: <url>" formatted comment for GitHub, the plain URL for
    other links, or None if nothing usable.
    """
    if not source_links_json:
        return None
    import json as _json
    try:
        links = _json.loads(source_links_json)
    except (ValueError, TypeError):
        return None
    if not isinstance(links, list) or not links:
        return None
    github = next((u for u in links if "github.com/" in (u or "")), None)
    if github:
        return f"GitHub: {github}"
    other_forge = next((u for u in links if any(s in (u or "") for s in ("gitlab.com/", "bitbucket.org/"))), None)
    if other_forge:
        return other_forge
    other = next((u for u in links if isinstance(u, str) and u.startswith(("http://", "https://"))), None)
    return other


def do_handoff(
    draft_id: int,
    *,
    threads_only: bool = False,
    as_draft: bool = False,
    force: bool = False,
) -> HandoffResult:
    """Push a saved draft to Postiz so it actually reaches Threads + Facebook.

    Used by both `orbit drafts handoff <id>` (where errors are fatal) and the
    `_schedule` flow inside `orbit draft` (where errors are non-fatal — the
    draft stays scheduled locally and the user can retry later).

    Pass `force=True` to re-handoff a draft that's already `handed_off_to_postiz`
    (used to repair posts that went out without media or comment links — delete
    the old Postiz posts in the UI first, then re-handoff).
    """
    db = DB()
    cfg = Config()
    rows = list(db.conn.query(
        "SELECT id, platform, content, publish_at, status, media_url, source_links FROM drafts WHERE id = ?",
        [draft_id],
    ))
    if not rows:
        return HandoffResult(False, f"No draft with id {draft_id}.")
    r = rows[0]
    allowed = {"scheduled", "draft"}
    if force:
        allowed.add("handed_off_to_postiz")
    if r["status"] not in allowed:
        hint = (
            " Pass --force to re-handoff (delete the old Postiz posts first)."
            if r["status"] == "handed_off_to_postiz"
            else ""
        )
        return HandoffResult(False, f"Draft {draft_id} is `{r['status']}` — nothing to hand off.{hint}")
    if not r["publish_at"]:
        return HandoffResult(False, f"Draft {draft_id} has no publish_at time.")

    try:
        postiz.ensure_available()
    except postiz.PostizUnavailable as e:
        return HandoffResult(False, str(e))

    # Route by draft.platform so LinkedIn drafts only go to LinkedIn and Threads
    # drafts go to Threads+Facebook. Threads drafts ≠ LinkedIn drafts — different
    # tone, length, hook style — so we never cross-post the wrong shape.
    targets: list[tuple[str, str, dict | None]] = []
    platform = r["platform"]

    if platform == "linkedin":
        li_id = postiz.integration_id_for("linkedin")
        if not li_id:
            return HandoffResult(False, "No LinkedIn integration found in Postiz. Connect it at https://postiz.com first.")
        # LinkedIn schema check (cmkdn... ): no required settings, maxLength 3000.
        # Pass None for settings; LinkedIn won't prompt in UI like Facebook does.
        targets.append(("linkedin", li_id, None))
    else:
        # Default = Threads draft. Goes to Threads (+ Facebook unless --threads-only).
        threads_id = postiz.integration_id_for("threads")
        if not threads_id:
            return HandoffResult(False, "No Threads integration found in Postiz. Connect it at https://postiz.com first.")
        targets.append(("threads", threads_id, None))
        if not threads_only:
            fb_id = postiz.integration_id_for("facebook")
            if fb_id:
                # Facebook's integration requires post_type. Keep source links
                # out of the main post/link-card surface; source links go only
                # as threaded comments via _pick_comment_link below.
                fb_settings: dict = {"post_type": "post"}
                targets.append(("facebook", fb_id, fb_settings))

    # If the draft has source media, download from X and upload to Postiz so
    # we can attach a uploads.postiz.com URL (Postiz rejects external URLs).
    # Cached on disk so re-handoff is free.
    media_url = r.get("media_url")
    postiz_media_url: str | None = None
    note = ""
    if media_url:
        from orbit import media_pipeline
        try:
            postiz_media_url = media_pipeline.attach_media(draft_id, media_url)
        except media_pipeline.MediaPipelineError as e:
            # Don't fail the whole handoff — proceed text-only — but make the
            # failure LOUD here (the success message scrolls past in batch runs).
            console.print(
                f"  [bold yellow]⚠ Draft {draft_id}: media upload failed — posting text-only.[/bold yellow]"
            )
            console.print(f"    [dim]{e}[/dim]")
            console.print(f"    [dim]Original media URL: {media_url}[/dim]")
            console.print(
                f"    [dim]Fix: delete the Postiz post and re-run[/dim] "
                f"[cyan]orbit drafts handoff {draft_id} --force[/cyan]"
            )
            note = f" [yellow](media skipped: {e})[/yellow]"

    when_iso = r["publish_at"].replace("+00:00", "Z")

    # If the source bookmark had a GitHub URL (or similar project link), add it
    # as a threaded comment so readers can find the project.
    comment = _pick_comment_link(r.get("source_links"))
    if not comment and r.get("source_links") in (None, "", "[]"):
        # Loud, but only when there's literally no source link at all. If we
        # have links and just none look like a forge, stay quiet.
        console.print(
            f"  [dim]Draft {draft_id}: no source link captured — no GitHub comment will be attached.[/dim]"
        )
        console.print(
            f"    [dim]If the tweet mentioned a project, set one with[/dim] "
            f"[cyan]orbit drafts comment {draft_id} <url>[/cyan][dim], then re-handoff.[/dim]"
        )

    # One Postiz call per integration so each gets the right --settings dict.
    # Two-target sends today: Threads (no settings) + Facebook ({post_type, url?}).
    posted: list[tuple[str, str]] = []
    failures: list[str] = []
    for name, iid, settings in targets:
        try:
            pid = postiz.schedule_post(
                content=r["content"],
                when_iso=when_iso,
                integration_ids=[iid],
                media_url=postiz_media_url,
                as_draft=as_draft,
                comment=comment,
                settings=settings,
            )
            posted.append((name, pid))
        except Exception as e:
            failures.append(f"{name}: {e}")

    if not posted:
        return HandoffResult(False, f"All Postiz targets failed — {'; '.join(failures)}")

    db.conn["drafts"].update(draft_id, {
        "status": "handed_off_to_postiz",
        "external_id": ",".join(pid for _, pid in posted),
    })
    target_list = "+".join(name for name, _ in posted)
    msg = f"Draft {draft_id} → Postiz ({target_list}, {when_iso}).{note}"
    if failures:
        msg += f" [yellow]Partial: {'; '.join(failures)}[/yellow]"
    return HandoffResult(
        True,
        msg,
        postiz_id=",".join(pid for _, pid in posted),
    )


def _pick_embed_url(source_links_json: str | None) -> str | None:
    """Pick a URL from source_links to use as the Facebook embed (link-card preview).
    Same preference as _pick_comment_link but returns the raw URL, not a formatted comment."""
    if not source_links_json:
        return None
    import json as _json
    try:
        links = _json.loads(source_links_json)
    except (ValueError, TypeError):
        return None
    if not isinstance(links, list) or not links:
        return None
    github = next((u for u in links if "github.com/" in (u or "")), None)
    if github:
        return github
    other_forge = next((u for u in links if any(s in (u or "") for s in ("gitlab.com/", "bitbucket.org/"))), None)
    return other_forge


@app.command("due")
def due(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would publish without doing it"),
) -> None:
    """Publish any scheduled drafts whose `publish_at` has passed."""
    cfg = Config()
    db = DB()
    now_iso = datetime.now(timezone.utc).isoformat()
    rows = list(db.conn.query(
        "SELECT id, content, publish_at FROM drafts "
        "WHERE platform = 'threads' AND status = 'scheduled' AND publish_at <= ? "
        "ORDER BY publish_at",
        [now_iso],
    ))
    if not rows:
        console.print("\n[dim]Nothing scheduled is due.[/dim]\n")
        return

    console.print(f"\n[bold]{len(rows)} draft(s) due:[/bold]")
    for r in rows:
        preview = (r["content"] or "")[:60].replace("\n", " ")
        console.print(f"  [cyan]{r['id']}[/cyan]  scheduled {r['publish_at']}  ·  {preview}…")

    if dry_run:
        console.print("\n[dim]Dry run — nothing posted.[/dim]\n")
        return

    token = cfg.get("threads.access_token")
    user_id = cfg.get("threads.user_id")
    if not token or not user_id:
        console.print("\n[red]✗ Threads not configured.[/red] Run: [cyan]orbit setup --platform threads[/cyan]\n")
        raise typer.Exit(1)
    client = ThreadsClient(access_token=token, user_id=user_id)

    posted = 0
    for r in rows:
        try:
            thread_id = client.create_post(r["content"])
        except Exception as e:
            console.print(f"  [red]✗ Draft {r['id']} failed: {e}[/red]")
            continue
        db.conn["drafts"].update(r["id"], {"status": "published"})
        db.conn["posts"].insert({
            "draft_id": r["id"],
            "platform": "threads",
            "external_id": thread_id,
            "published_at": datetime.now(timezone.utc).isoformat(),
        })
        console.print(f"  [green]✓ Draft {r['id']} → thread {thread_id}[/green]")
        posted += 1
    console.print(f"\n[green]Posted {posted} of {len(rows)}.[/green]\n")


def _color_status(status: str | None) -> str:
    palette = {
        "draft": "[yellow]draft[/yellow]",
        "scheduled": "[cyan]scheduled[/cyan]",
        "published": "[green]published[/green]",
    }
    return palette.get(status or "", status or "—")
