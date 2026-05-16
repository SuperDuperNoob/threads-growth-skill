from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from orbit.config import Config
from orbit.db import DB
from orbit.patterns import PatternStore
from orbit.platforms.linkedin import LinkedInClient
from orbit.platforms.youtube import YouTubeClient

app = typer.Typer(help="Pull metrics from connected platforms")
console = Console()


@app.callback(invoke_without_command=True)
def sync(
    platform: Optional[str] = typer.Option(
        None, "--platform", "-p", help="Sync one platform only"
    ),
) -> None:
    cfg = Config()
    db = DB()
    ps = PatternStore()
    now = datetime.now(timezone.utc).isoformat()
    targets = [platform] if platform else ["linkedin", "youtube"]

    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as progress:
        for target in targets:
            task = progress.add_task(f"Syncing {target}...", total=None)
            try:
                if target == "linkedin":
                    _sync_linkedin(cfg, db, ps, now)
                elif target == "youtube":
                    _sync_youtube(cfg, db, ps, now)
                else:
                    console.print(f"[yellow]{target} sync not yet implemented[/yellow]")
                progress.update(
                    task,
                    description=f"[green]✓ {target} synced[/green]",
                    completed=True,
                )
            except Exception as e:
                progress.update(
                    task,
                    description=f"[red]✗ {target} failed: {e}[/red]",
                    completed=True,
                )

    console.print(
        "\n[bold green]Sync complete.[/bold green] "
        "Run [cyan]orbit insights[/cyan] to see what changed."
    )


def _sync_linkedin(cfg: Config, db: DB, ps: PatternStore, now: str) -> None:
    token = cfg.get("linkedin.access_token")
    author_urn = cfg.get("linkedin.author_urn")
    if not token or not author_urn:
        raise ValueError("LinkedIn not configured. Run: orbit setup --platform linkedin")

    client = LinkedInClient(access_token=token)
    posts = client.get_posts(author_urn=author_urn)

    for post in posts:
        existing = list(db.conn["posts"].rows_where("external_id = ?", [post["external_id"]]))
        if not existing:
            idea_id = db.conn["ideas"].insert(
                {
                    "title": post["content"][:100],
                    "source": "sync",
                    "status": "published",
                    "created_at": post["published_at"],
                }
            ).last_pk
            draft_id = db.conn["drafts"].insert(
                {
                    "idea_id": idea_id,
                    "platform": "linkedin",
                    "content": post["content"],
                    "status": "published",
                    "created_at": post["published_at"],
                }
            ).last_pk
            db.conn["posts"].insert(
                {
                    "draft_id": draft_id,
                    "platform": "linkedin",
                    "external_id": post["external_id"],
                    "published_at": post["published_at"],
                }
            )

    all_posts = list(db.conn["posts"].rows_where("platform = ?", ["linkedin"]))
    urns = [p["external_id"] for p in all_posts if p["external_id"]]
    if urns:
        metrics_map = client.get_metrics(urns)
        for post_row in all_posts:
            m = metrics_map.get(post_row["external_id"])
            if m:
                db.conn["metrics"].insert(
                    {**m, "post_id": post_row["id"], "platform": "linkedin", "pulled_at": now}
                )

    ps.recalculate("linkedin", db)


def _sync_youtube(cfg: Config, db: DB, ps: PatternStore, now: str) -> None:
    api_key = cfg.get("youtube.api_key")
    channel_id = cfg.get("youtube.channel_id")
    if not api_key or not channel_id:
        raise ValueError("YouTube not configured. Run: orbit setup --platform youtube")

    client = YouTubeClient(api_key=api_key, channel_id=channel_id)
    videos = client.get_videos()

    for video in videos:
        existing = list(db.conn["posts"].rows_where("external_id = ?", [video["external_id"]]))
        if not existing:
            idea_id = db.conn["ideas"].insert(
                {
                    "title": video["content"],
                    "source": "sync",
                    "status": "published",
                    "created_at": video["published_at"],
                }
            ).last_pk
            draft_id = db.conn["drafts"].insert(
                {
                    "idea_id": idea_id,
                    "platform": "youtube",
                    "content": video["content"],
                    "status": "published",
                    "created_at": video["published_at"],
                }
            ).last_pk
            db.conn["posts"].insert(
                {
                    "draft_id": draft_id,
                    "platform": "youtube",
                    "external_id": video["external_id"],
                    "published_at": video["published_at"],
                }
            )

    all_posts = list(db.conn["posts"].rows_where("platform = ?", ["youtube"]))
    metrics_map = client.extract_metrics(videos)
    for post_row in all_posts:
        m = metrics_map.get(post_row["external_id"])
        if m:
            db.conn["metrics"].insert(
                {**m, "post_id": post_row["id"], "platform": "youtube", "pulled_at": now}
            )

    ps.recalculate("youtube", db)
