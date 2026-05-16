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
                "created_at": str,
            }, pk="id", not_null={"platform", "status"},
               foreign_keys=[("idea_id", "ideas", "id")])

        if "posts" not in self.conn.table_names():
            self.conn["posts"].create({
                "id": int,
                "draft_id": int,
                "platform": str,
                "external_id": str,
                "published_at": str,
            }, pk="id", not_null={"platform"},
               foreign_keys=[("draft_id", "drafts", "id")])

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
