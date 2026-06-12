from pathlib import Path
import sqlite_utils

class DB:
    def __init__(self, home: Path | None = None):
        home = home or Path.home() / ".orbit"
        home.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite_utils.Database(home / "orbit.db")
        self._migrate()

    def _migrate(self):
        if "ideas" not in self.conn.table_names():
            self.conn["ideas"].create({
                "id": int,
                "title": str,
                "source": str,
                "status": str,
                "score_linkedin": float,
                "score_threads": float,
                "score_facebook": float,
                "score_substack": float,
                "score_youtube": float,
                "created_at": str,
            }, pk="id", not_null={"title", "source", "status"})

        if "drafts" not in self.conn.table_names():
            self.conn["drafts"].create({
                "id": int,
                "idea_id": int,
                "platform": str,
                "content": str,
                "hook_type": str,
                "status": str,
                "publish_at": str,
                "source_url": str,
                "media_url": str,
                "media_type": str,
                "media_path": str,
                "external_id": str,
                "created_at": str,
            }, pk="id", not_null={"platform", "status"},
               foreign_keys=[("idea_id", "ideas", "id")])
        else:
            existing = {c.name for c in self.conn["drafts"].columns}
            for col in (
                "publish_at", "source_url", "media_url", "media_type",
                "media_path", "external_id", "source_links",
            ):
                if col not in existing:
                    self.conn["drafts"].add_column(col, str)

        if "posts" not in self.conn.table_names():
            self.conn["posts"].create({
                "id": int,
                "draft_id": int,
                "platform": str,
                "external_id": str,
                "published_at": str,
                "embedding": bytes,
                "embedding_model": str,
            }, pk="id", not_null={"platform"},
               foreign_keys=[("draft_id", "drafts", "id")])
        else:
            existing_post_cols = {c.name for c in self.conn["posts"].columns}
            if "embedding" not in existing_post_cols:
                self.conn["posts"].add_column("embedding", bytes)
            if "embedding_model" not in existing_post_cols:
                self.conn["posts"].add_column("embedding_model", str)

        if "metrics" not in self.conn.table_names():
            self.conn["metrics"].create({
                "id": int,
                "post_id": int,
                "platform": str,
                "views": int,
                "likes": int,
                "comments": int,
                "shares": int,
                "reposts": int,
                "clicks": int,
                "saves": int,
                "pulled_at": str,
            }, pk="id", not_null={"platform"},
               foreign_keys=[("post_id", "posts", "id")])

        if "discoveries" not in self.conn.table_names():
            self.conn["discoveries"].create({
                "id": int,
                "tweet_id": str,
                "author": str,
                "url": str,
                "text": str,
                "media_url": str,
                "media_type": str,
                "source_likes": int,
                "source_retweets": int,
                "source_views": int,
                "score": int,
                "score_reasoning": str,
                "fetched_at": str,
                "status": str,  # 'new', 'drafted', 'dismissed'
            }, pk="id", not_null={"tweet_id", "url", "status"})
            # Unique on tweet_id so we don't re-store the same candidate
            self.conn["discoveries"].create_index(["tweet_id"], unique=True)

        if "youtube_projects" not in self.conn.table_names():
            self.conn["youtube_projects"].create({
                "id": int,
                "idea_id": int,
                "status": str,
                "topic": str,
                "packaging_brief": str,
                "script": str,
                "external_id": str,
                "published_at": str,
            }, pk="id", not_null={"status"},
               foreign_keys=[("idea_id", "ideas", "id")])

        if "youtube_checklists" not in self.conn.table_names():
            self.conn["youtube_checklists"].create({
                "id": int,
                "title": str,
                "status": str,  # 'in_progress', 'shipped', 'abandoned'
                "video_id": str,  # YouTube video id once published
                "created_at": str,
                "shipped_at": str,
            }, pk="id", not_null={"title", "status"})

        if "youtube_checklist_items" not in self.conn.table_names():
            self.conn["youtube_checklist_items"].create({
                "id": int,
                "checklist_id": int,
                "phase": str,           # 'pre-production', 'scripting', 'filming', 'post-production'
                "order_idx": int,       # display order within the checklist
                "label": str,
                "detail": str,
                "blocks_next": int,     # 0/1 — if 1, downstream items can't be checked
                "completed_at": str,    # ISO timestamp, NULL if pending
                "notes": str,           # user's freeform notes per item
            }, pk="id", not_null={"checklist_id", "phase", "label"},
               foreign_keys=[("checklist_id", "youtube_checklists", "id")])
