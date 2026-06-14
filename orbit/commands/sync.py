from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from orbit.config import Config
from orbit.db import DB, evaluate_staleness, last_metric_pull_per_platform
from orbit.patterns import PatternStore
from orbit.platforms.linkedin import LinkedInClient
from orbit.platforms.threads import ThreadsClient
from orbit.platforms.youtube import YouTubeClient
from orbit.reports import write_winning_formats_for_threads
from orbit.embeddings import EMBEDDING_MODEL, embed_texts, pack_embedding

app = typer.Typer(help="Pull metrics from connected platforms")
console = Console()

# Warn when a platform's newest metric is older than this. Threads syncs ~daily;
# a 3-day gap means a token died or a platform is failing silently (see the
# 2026-05 LinkedIn/YouTube outage that sat unnoticed for ~3 weeks).
STALE_AFTER_DAYS = 3


@app.callback(invoke_without_command=True)
def sync(
    platform: Optional[str] = typer.Option(
        None, "--platform", "-p", help="Sync one platform only"
    ),
) -> None:
    cfg = Config()
    db = DB()
    ps = PatternStore()
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    targets = [platform] if platform else ["linkedin", "youtube", "threads"]

    # Collect failures so we can print them LOUDLY after the progress bar tears
    # down — a dim spinner line scrolls away and is how the 2026-05 outage went
    # unnoticed for ~3 weeks.
    failures: list[tuple[str, str]] = []

    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as progress:
        for target in targets:
            task = progress.add_task(f"Syncing {target}...", total=None)
            try:
                if target == "linkedin":
                    _sync_linkedin(cfg, db, ps, now)
                elif target == "youtube":
                    _sync_youtube(cfg, db, ps, now)
                elif target == "threads":
                    _sync_threads(cfg, db, ps, now)
                else:
                    console.print(f"[yellow]{target} sync not yet implemented[/yellow]")
                progress.update(
                    task,
                    description=f"[green]✓ {target} synced[/green]",
                    completed=True,
                )
            except Exception as e:
                summary = _summarize_sync_error(target, e)
                failures.append((target, summary))
                progress.update(
                    task,
                    description=f"[yellow]⊘ {target} skipped: {summary}[/yellow]",
                    completed=True,
                )

    # Loud, persistent failure recap — survives after the spinner is gone.
    for target, summary in failures:
        console.print(f"[bold yellow]⚠ {target} did NOT sync:[/bold yellow] {summary}")

    _warn_if_stale(db, now_dt, targets)

    console.print(
        "\n[bold green]Sync complete.[/bold green] "
        "Run [cyan]orbit status[/cyan] to see what changed."
    )


def _warn_if_stale(db: DB, now_dt: datetime, targets: list[str]) -> None:
    """Print a loud warning for any platform whose newest metric is stale.

    Catches silent multi-week outages: even when a sync 'succeeds' (no exception)
    it can quietly stop recording fresh metrics if the upstream data froze.
    """
    last_pulls = last_metric_pull_per_platform(db.conn)
    staleness = evaluate_staleness(
        last_pulls, now=now_dt, platforms=targets, stale_after_days=STALE_AFTER_DAYS
    )
    for platform, info in staleness.items():
        if not info["stale"]:
            continue
        if info["never"]:
            console.print(
                f"[bold yellow]⚠ {platform}: no metrics ever recorded[/bold yellow] "
                f"— sync has never successfully pulled data."
            )
        else:
            console.print(
                f"[bold yellow]⚠ {platform}: last fresh metric was "
                f"{info['days']:.0f} days ago[/bold yellow] "
                f"(threshold {STALE_AFTER_DAYS}d) — likely a dead token or disabled app. "
                f"Try [cyan]orbit setup --platform {platform}[/cyan]."
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
        # Impressions/clicks come back batched for ALL posts via shareStatistics.
        # likes/comments need a per-URN socialActions call (no batch endpoint), so
        # we only enrich the 50 most-recent posts — the ones we actually analyze —
        # to avoid 700+ extra calls per sync. Older posts keep impressions-only.
        recent = sorted(
            (p for p in all_posts if p["external_id"]),
            key=lambda p: p.get("published_at") or "",
            reverse=True,
        )[:50]
        enrich_urns = [p["external_id"] for p in recent]

        # One batched shareStatistics call covers impressions for every post.
        metrics_map = client.get_metrics(urns, enrich_social=False)
        # Then enrich only the recent 50 with per-URN like/comment counts.
        client.enrich_social_counts(metrics_map, enrich_urns)
        for post_row in all_posts:
            m = metrics_map.get(post_row["external_id"])
            if m:
                already_pulled = list(db.conn["metrics"].rows_where(
                    "post_id = ? AND pulled_at = ?", [post_row["id"], now]
                ))
                if not already_pulled:
                    db.conn["metrics"].insert(
                        {**m, "post_id": post_row["id"], "platform": "linkedin", "pulled_at": now}
                    )

    ps.recalculate("linkedin", db)


def _sync_youtube(cfg: Config, db: DB, ps: PatternStore, now: str) -> None:
    access_token = cfg.get("youtube.access_token")
    channel_id = cfg.get("youtube.channel_id")
    if not access_token or not channel_id:
        raise ValueError("YouTube not configured. Run: orbit setup --platform youtube")

    client = YouTubeClient(
        access_token=access_token,
        channel_id=channel_id,
        client_id=cfg.get("youtube.client_id"),
        client_secret=cfg.get("youtube.client_secret"),
        refresh_token=cfg.get("youtube.refresh_token"),
        # Persist refreshed tokens so subsequent runs don't start with the dead one
        on_token_refresh=lambda new_token: cfg.set("youtube.access_token", new_token),
    )
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
    # `get_videos` now paginates the full channel history (see youtube.py), so
    # every stored post should appear here — not just the most recent 50.
    metrics_map = {v["external_id"]: v for v in videos}
    for post_row in all_posts:
        v = metrics_map.get(post_row["external_id"])
        if v:
            m = client.extract_metrics([v])[v["external_id"]]
            already_pulled = list(db.conn["metrics"].rows_where(
                "post_id = ? AND pulled_at = ?", [post_row["id"], now]
            ))
            if not already_pulled:
                db.conn["metrics"].insert(
                    {**m, "post_id": post_row["id"], "platform": "youtube", "pulled_at": now}
                )

    ps.recalculate("youtube", db)


def _sync_threads(cfg: Config, db: DB, ps: PatternStore, now: str) -> None:
    token = cfg.get("threads.access_token")
    user_id = cfg.get("threads.user_id")
    if not token or not user_id:
        raise ValueError("Threads not configured. Run: orbit setup --platform threads")

    # Warn (don't fail) when the stored token is about to expire so the user
    # can refresh before sync starts failing silently.
    from orbit.platforms.meta_token import days_until_expiry
    days = days_until_expiry(cfg.get("threads.token_expires_at"))
    if days is not None and days <= 7:
        console.print(
            f"  [yellow]⚠ Threads token expires in {days} day(s). "
            f"Regenerate via Graph API Explorer + `orbit setup --platform threads`.[/yellow]"
        )

    client = ThreadsClient(access_token=token, user_id=user_id)
    posts = client.get_posts()

    for post in posts:
        existing = list(db.conn["posts"].rows_where("external_id = ?", [post["external_id"]]))
        if not existing:
            # Check if a draft already exists for this content (published via Postiz
            # or another tool). If so, reuse it — preserving its source_links.
            content_stripped = post["content"].strip()
            existing_draft = list(db.conn.execute(
                "SELECT id FROM drafts WHERE platform='threads' AND trim(content) = ? LIMIT 1",
                [content_stripped]
            ).fetchall())

            if existing_draft:
                draft_id = existing_draft[0][0]
                # Mark it published so it reflects reality
                db.conn["drafts"].update(draft_id, {"status": "published"})
            else:
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
                        "platform": "threads",
                        "content": post["content"],
                        "status": "published",
                        "created_at": post["published_at"],
                    }
                ).last_pk

            db.conn["posts"].insert(
                {
                    "draft_id": draft_id,
                    "platform": "threads",
                    "external_id": post["external_id"],
                    "published_at": post["published_at"],
                }
            )

    all_posts = list(db.conn["posts"].rows_where("platform = ?", ["threads"]))
    for post_row in all_posts:
        already_pulled = list(db.conn["metrics"].rows_where(
            "post_id = ? AND pulled_at = ?", [post_row["id"], now]
        ))
        if not already_pulled:
            try:
                m = client.get_metrics(post_row["external_id"])
                db.conn["metrics"].insert(
                    {**m, "post_id": post_row["id"], "platform": "threads", "pulled_at": now}
                )
            except Exception:
                pass

    ps.recalculate("threads", db)

    # Backfill embeddings for any Threads posts missing them. Embeddings power
    # bookmark-to-winner similarity scoring in `orbit draft`. Failure here should
    # not break sync — the draft path falls back to first-N selection if a winner
    # has no embedding.
    try:
        _backfill_threads_embeddings(db)
    except Exception as e:
        console.print(f"  [yellow]⚠ embeddings not generated: {e}[/yellow]")

    # Regenerate the skill's personal performance database (see SKILL.md).
    # No-op when run outside the skill checkout — see find_repo_root.
    try:
        out = write_winning_formats_for_threads(db)
        if out is not None:
            console.print(f"  [dim]Updated {out.relative_to(out.parents[1])}[/dim]")
    except Exception as e:
        console.print(f"  [yellow]⚠ winning-formats.md not regenerated: {e}[/yellow]")


def _backfill_threads_embeddings(db: DB, *, batch_size: int = 64) -> int:
    """Embed any Threads posts that don't yet have a vector for the current model.

    Returns the count newly embedded. Uses the post's draft content as input.
    Batches into one API call per `batch_size` posts to keep costs / latency low.
    """
    rows = db.conn.execute(f"""
        SELECT p.id, d.content
        FROM posts p
        JOIN drafts d ON d.id = p.draft_id
        WHERE p.platform = 'threads'
          AND (p.embedding IS NULL OR p.embedding_model != ?)
          AND d.content IS NOT NULL AND length(d.content) > 0
    """, [EMBEDDING_MODEL]).fetchall()

    if not rows:
        return 0

    console.print(f"  [dim]Embedding {len(rows)} Threads post(s)...[/dim]")
    total = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        ids = [r[0] for r in batch]
        texts = [r[1] for r in batch]
        vectors = embed_texts(texts)
        for post_id, vec in zip(ids, vectors):
            if not vec:
                continue
            db.conn["posts"].update(post_id, {
                "embedding": pack_embedding(vec),
                "embedding_model": EMBEDDING_MODEL,
            })
            total += 1
    return total


def _summarize_sync_error(platform: str, err: Exception) -> str:
    """Translate raw HTTP/SDK errors into a short, actionable one-liner.

    Long URLs and HTML error pages flood the terminal; we strip them and
    map well-known auth failures to a friendly skip reason so the user
    knows what to fix without re-reading the LinkedIn/Meta error spec.
    """
    msg = str(err)

    # LinkedIn 403 ACCESS_DENIED — token has profile scope but not r_member_social
    if "403" in msg and "linkedin" in msg.lower():
        return "LinkedIn token lacks read scope (re-auth with r_member_social, or skip)"
    if "ACCESS_DENIED" in msg:
        return f"access denied — token scopes don't include this resource"

    # Meta/Threads expired token
    if "Session has expired" in msg or '"code":190' in msg:
        return "Threads token expired — regenerate via Graph API Explorer, then `orbit setup --platform threads`"

    # Meta/Threads generic 400 from the Graph API
    if "graph.threads.net" in msg or "graph.facebook.com" in msg:
        return f"{platform} Graph API error — check token + permissions (`orbit setup --platform {platform}`)"

    # Google OAuth (YouTube) expired token — refresh_token machinery should handle
    # this but sometimes fails; tell the user to re-auth.
    if "401" in msg and ("googleapis" in msg or platform == "youtube"):
        return "YouTube token expired — `orbit setup --platform youtube` to re-auth"

    # Truncate everything else so we don't dump a 500-char URL into the spinner
    short = msg.splitlines()[0]
    if len(short) > 120:
        short = short[:117] + "…"
    return short
