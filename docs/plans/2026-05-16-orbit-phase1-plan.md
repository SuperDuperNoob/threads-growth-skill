# Orbit CLI Phase 1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the foundation of Orbit — project scaffold, SQLite database, `orbit setup` wizard, and `orbit sync` for LinkedIn and YouTube with basic pattern file generation.

**Architecture:** Python CLI using Typer for commands and Rich for terminal output. All data lives in `~/.orbit/orbit.db` (SQLite via sqlite-utils). Pattern files are JSON in `~/.orbit/patterns/`. API credentials stored in `~/.orbit/config.json`. The CLI is installed as a local package via `pip install -e .`.

**Tech Stack:** Python 3.11+, Typer, Rich, sqlite-utils, httpx, anthropic SDK, python-dotenv

**Worktree:** `/Users/keithrumjahn/Desktop/threads-growth-skill/.worktrees/orbit-phase1`

---

## Project Structure (target)

```
orbit/
  __init__.py
  cli.py              # Typer app entry point, registers all command groups
  db.py               # Database init, migrations, helper queries
  config.py           # Config read/write (~/.orbit/config.json)
  patterns.py         # Pattern file read/write/recalculate
  platforms/
    __init__.py
    linkedin.py       # LinkedIn API client
    youtube.py        # YouTube API client
  commands/
    __init__.py
    setup.py          # orbit setup
    sync.py           # orbit sync
tests/
  conftest.py
  test_db.py
  test_config.py
  test_patterns.py
  test_sync_linkedin.py
  test_sync_youtube.py
pyproject.toml
```

---

### Task 1: Project Scaffold

**Files:**
- Create: `orbit/__init__.py`
- Create: `orbit/cli.py`
- Create: `orbit/commands/__init__.py`
- Create: `orbit/platforms/__init__.py`
- Create: `tests/conftest.py`
- Create: `pyproject.toml`

**Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "orbit"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "typer>=0.12",
    "rich>=13",
    "sqlite-utils>=3.36",
    "httpx>=0.27",
    "anthropic>=0.28",
    "python-dotenv>=1.0",
]

[project.scripts]
orbit = "orbit.cli:app"

[tool.setuptools.packages.find]
where = ["."]
include = ["orbit*"]
```

**Step 2: Create orbit/__init__.py**

```python
```
(empty file)

**Step 3: Create orbit/cli.py**

```python
import typer
from orbit.commands import setup, sync

app = typer.Typer(help="Orbit — content flywheel CLI")
app.add_typer(setup.app, name="setup")
app.add_typer(sync.app, name="sync")

if __name__ == "__main__":
    app()
```

**Step 4: Create orbit/commands/__init__.py and orbit/platforms/__init__.py**

Both empty files.

**Step 5: Create tests/conftest.py**

```python
import pytest
import tempfile
import os
from pathlib import Path

@pytest.fixture
def orbit_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ORBIT_HOME", str(tmp_path))
    return tmp_path
```

**Step 6: Install the package**

```bash
pip install -e ".[dev]" 2>/dev/null || pip install -e .
```

**Step 7: Verify CLI loads**

```bash
orbit --help
```
Expected: Shows help text with `setup` and `sync` commands listed.

**Step 8: Commit**

```bash
git add pyproject.toml orbit/ tests/
git commit -m "feat: scaffold orbit CLI project structure"
```

---

### Task 2: Config Module

**Files:**
- Create: `orbit/config.py`
- Create: `tests/test_config.py`

**Step 1: Write failing tests**

```python
# tests/test_config.py
import pytest
import json
from orbit.config import Config

def test_config_creates_dir(orbit_home):
    cfg = Config(orbit_home)
    assert (orbit_home / "config.json").exists()

def test_config_get_missing_key(orbit_home):
    cfg = Config(orbit_home)
    assert cfg.get("linkedin.client_id") is None

def test_config_set_and_get(orbit_home):
    cfg = Config(orbit_home)
    cfg.set("linkedin.client_id", "abc123")
    assert cfg.get("linkedin.client_id") == "abc123"

def test_config_persists(orbit_home):
    cfg = Config(orbit_home)
    cfg.set("youtube.api_key", "yt-key")
    cfg2 = Config(orbit_home)
    assert cfg2.get("youtube.api_key") == "yt-key"
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_config.py -v
```
Expected: FAIL with `ModuleNotFoundError` or `ImportError`

**Step 3: Implement orbit/config.py**

```python
import json
from pathlib import Path

class Config:
    def __init__(self, home: Path = None):
        self.home = home or Path.home() / ".orbit"
        self.home.mkdir(parents=True, exist_ok=True)
        self._path = self.home / "config.json"
        if not self._path.exists():
            self._path.write_text("{}")
        self._data = json.loads(self._path.read_text())

    def get(self, key: str):
        parts = key.split(".")
        node = self._data
        for part in parts:
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    def set(self, key: str, value):
        parts = key.split(".")
        node = self._data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
        self._path.write_text(json.dumps(self._data, indent=2))
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_config.py -v
```
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add orbit/config.py tests/test_config.py
git commit -m "feat: add Config module with dot-notation get/set"
```

---

### Task 3: Database Module

**Files:**
- Create: `orbit/db.py`
- Create: `tests/test_db.py`

**Step 1: Write failing tests**

```python
# tests/test_db.py
import pytest
from orbit.db import DB

def test_db_creates_file(orbit_home):
    db = DB(orbit_home)
    assert (orbit_home / "orbit.db").exists()

def test_db_has_all_tables(orbit_home):
    db = DB(orbit_home)
    tables = db.conn.table_names()
    assert "ideas" in tables
    assert "drafts" in tables
    assert "posts" in tables
    assert "metrics" in tables
    assert "youtube_projects" in tables

def test_insert_and_fetch_idea(orbit_home):
    db = DB(orbit_home)
    db.conn["ideas"].insert({
        "title": "Test idea",
        "source": "user",
        "status": "pending",
    })
    row = list(db.conn["ideas"].rows)[0]
    assert row["title"] == "Test idea"
    assert row["source"] == "user"
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_db.py -v
```
Expected: FAIL with import error

**Step 3: Implement orbit/db.py**

```python
from pathlib import Path
import sqlite_utils

class DB:
    def __init__(self, home: Path = None):
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
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_db.py -v
```
Expected: 3 PASSED

**Step 5: Commit**

```bash
git add orbit/db.py tests/test_db.py
git commit -m "feat: add DB module with SQLite schema and migrations"
```

---

### Task 4: Pattern Files Module

**Files:**
- Create: `orbit/patterns.py`
- Create: `tests/test_patterns.py`

**Step 1: Write failing tests**

```python
# tests/test_patterns.py
import pytest
import json
from orbit.patterns import PatternStore

def test_pattern_store_creates_dir(orbit_home):
    ps = PatternStore(orbit_home)
    assert (orbit_home / "patterns").exists()

def test_load_missing_platform_returns_defaults(orbit_home):
    ps = PatternStore(orbit_home)
    p = ps.load("linkedin")
    assert p["platform"] == "linkedin"
    assert p["sample_size"] == 0
    assert p["top_hooks"] == []

def test_save_and_load_pattern(orbit_home):
    ps = PatternStore(orbit_home)
    data = {
        "platform": "threads",
        "sample_size": 10,
        "top_hooks": [{"type": "anti_demo", "avg_multiplier": 2.1, "sample": 4}],
        "optimal_length": {"min": 80, "max": 150, "unit": "words"},
        "best_posting_times": [],
        "top_topics": ["ai_agents"],
        "weak_topics": [],
        "ai_tone_flags": [],
        "engagement_benchmarks": {"views_median": 0, "likes_median": 0, "comments_median": 0},
    }
    ps.save("threads", data)
    loaded = ps.load("threads")
    assert loaded["sample_size"] == 10
    assert loaded["top_hooks"][0]["type"] == "anti_demo"
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_patterns.py -v
```
Expected: FAIL with import error

**Step 3: Implement orbit/patterns.py**

```python
import json
from pathlib import Path
from datetime import datetime, timezone

DEFAULTS = {
    "sample_size": 0,
    "top_hooks": [],
    "optimal_length": {"min": 50, "max": 300, "unit": "words"},
    "best_posting_times": [],
    "top_topics": [],
    "weak_topics": [],
    "ai_tone_flags": [],
    "engagement_benchmarks": {"views_median": 0, "likes_median": 0, "comments_median": 0},
}

class PatternStore:
    def __init__(self, home: Path = None):
        self.home = home or Path.home() / ".orbit"
        self.patterns_dir = self.home / "patterns"
        self.patterns_dir.mkdir(parents=True, exist_ok=True)

    def load(self, platform: str) -> dict:
        path = self.patterns_dir / f"{platform}.json"
        if not path.exists():
            return {"platform": platform, "updated_at": None, **DEFAULTS}
        return json.loads(path.read_text())

    def save(self, platform: str, data: dict):
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        path = self.patterns_dir / f"{platform}.json"
        path.write_text(json.dumps(data, indent=2))

    def recalculate(self, platform: str, db) -> dict:
        """Compute patterns from DB metrics for a platform. Returns updated pattern dict."""
        from collections import defaultdict
        import statistics

        posts = list(db.conn.execute("""
            SELECT p.id, p.published_at, d.hook_type, d.content,
                   m.views, m.likes, m.comments, m.reposts
            FROM posts p
            JOIN drafts d ON d.id = p.draft_id
            LEFT JOIN metrics m ON m.post_id = p.id
            WHERE p.platform = ?
            ORDER BY m.pulled_at DESC
        """, [platform]).fetchall())

        if not posts:
            return self.load(platform)

        views = [r[4] or 0 for r in posts]
        likes = [r[5] or 0 for r in posts]
        comments = [r[6] or 0 for r in posts]

        hook_scores = defaultdict(list)
        for r in posts:
            hook_type = r[2] or "unknown"
            hook_scores[hook_type].append(r[4] or 0)

        median_views = statistics.median(views) if views else 0
        top_hooks = sorted([
            {
                "type": ht,
                "avg_multiplier": round((sum(scores) / len(scores)) / median_views, 2) if median_views else 1.0,
                "sample": len(scores),
            }
            for ht, scores in hook_scores.items()
        ], key=lambda x: x["avg_multiplier"], reverse=True)

        pattern = self.load(platform)
        pattern.update({
            "sample_size": len(posts),
            "top_hooks": top_hooks,
            "engagement_benchmarks": {
                "views_median": median_views,
                "likes_median": statistics.median(likes) if likes else 0,
                "comments_median": statistics.median(comments) if comments else 0,
            },
        })
        self.save(platform, pattern)
        return pattern
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_patterns.py -v
```
Expected: 3 PASSED

**Step 5: Commit**

```bash
git add orbit/patterns.py tests/test_patterns.py
git commit -m "feat: add PatternStore for per-platform pattern files"
```

---

### Task 5: LinkedIn API Client

**Files:**
- Create: `orbit/platforms/linkedin.py`
- Create: `tests/test_sync_linkedin.py`

**Step 1: Write failing tests (using httpx mock)**

```python
# tests/test_sync_linkedin.py
import pytest
import httpx
from unittest.mock import patch, MagicMock
from orbit.platforms.linkedin import LinkedInClient

@pytest.fixture
def client():
    return LinkedInClient(access_token="test-token")

def test_client_requires_token():
    with pytest.raises(ValueError):
        LinkedInClient(access_token=None)

def test_get_posts_returns_list(client):
    mock_response = {
        "elements": [
            {
                "id": "urn:li:share:123",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {"text": "Test post content"}
                    }
                },
                "created": {"time": 1700000000000},
            }
        ]
    }
    with patch.object(client._http, "get") as mock_get:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: mock_response,
            raise_for_status=lambda: None,
        )
        posts = client.get_posts(author_urn="urn:li:person:abc")
    assert len(posts) == 1
    assert posts[0]["external_id"] == "urn:li:share:123"
    assert posts[0]["platform"] == "linkedin"

def test_get_metrics_returns_dict(client):
    mock_response = {
        "elements": [
            {
                "organizationalEntity": "urn:li:share:123",
                "totalShareStatistics": {
                    "impressionCount": 1500,
                    "likeCount": 42,
                    "commentCount": 7,
                    "shareCount": 3,
                    "clickCount": 89,
                }
            }
        ]
    }
    with patch.object(client._http, "get") as mock_get:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: mock_response,
            raise_for_status=lambda: None,
        )
        metrics = client.get_metrics(["urn:li:share:123"])
    assert metrics["urn:li:share:123"]["views"] == 1500
    assert metrics["urn:li:share:123"]["likes"] == 42
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_sync_linkedin.py -v
```
Expected: FAIL with import error

**Step 3: Implement orbit/platforms/linkedin.py**

```python
import httpx
from datetime import datetime, timezone

BASE_URL = "https://api.linkedin.com/v2"

class LinkedInClient:
    def __init__(self, access_token: str):
        if not access_token:
            raise ValueError("LinkedIn access_token is required")
        self._http = httpx.Client(
            headers={
                "Authorization": f"Bearer {access_token}",
                "LinkedIn-Version": "202401",
            },
            timeout=30,
        )

    def get_posts(self, author_urn: str, count: int = 50) -> list[dict]:
        resp = self._http.get(
            f"{BASE_URL}/ugcPosts",
            params={"q": "authors", "authors": f"List({author_urn})", "count": count},
        )
        resp.raise_for_status()
        elements = resp.json().get("elements", [])
        posts = []
        for el in elements:
            content = el.get("specificContent", {}).get(
                "com.linkedin.ugc.ShareContent", {}
            )
            text = content.get("shareCommentary", {}).get("text", "")
            created_ms = el.get("created", {}).get("time", 0)
            created_at = datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc).isoformat()
            posts.append({
                "external_id": el["id"],
                "platform": "linkedin",
                "content": text,
                "published_at": created_at,
            })
        return posts

    def get_metrics(self, post_urns: list[str]) -> dict[str, dict]:
        urns_param = ",".join(post_urns)
        resp = self._http.get(
            f"{BASE_URL}/organizationalEntityShareStatistics",
            params={"q": "organizationalEntity", "shares": f"List({urns_param})"},
        )
        resp.raise_for_status()
        result = {}
        for el in resp.json().get("elements", []):
            urn = el["organizationalEntity"]
            stats = el.get("totalShareStatistics", {})
            result[urn] = {
                "views": stats.get("impressionCount", 0),
                "likes": stats.get("likeCount", 0),
                "comments": stats.get("commentCount", 0),
                "shares": stats.get("shareCount", 0),
                "clicks": stats.get("clickCount", 0),
                "reposts": 0,
                "saves": 0,
            }
        return result
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_sync_linkedin.py -v
```
Expected: 3 PASSED

**Step 5: Commit**

```bash
git add orbit/platforms/linkedin.py tests/test_sync_linkedin.py
git commit -m "feat: add LinkedIn API client for posts and metrics"
```

---

### Task 6: YouTube API Client

**Files:**
- Create: `orbit/platforms/youtube.py`
- Create: `tests/test_sync_youtube.py`

**Step 1: Write failing tests**

```python
# tests/test_sync_youtube.py
import pytest
from unittest.mock import patch, MagicMock
from orbit.platforms.youtube import YouTubeClient

@pytest.fixture
def client():
    return YouTubeClient(api_key="test-key", channel_id="UC123")

def test_client_requires_api_key():
    with pytest.raises(ValueError):
        YouTubeClient(api_key=None, channel_id="UC123")

def test_get_videos_returns_list(client):
    mock_search = {
        "items": [{"id": {"videoId": "vid123"}}]
    }
    mock_details = {
        "items": [{
            "id": "vid123",
            "snippet": {"title": "Test Video", "publishedAt": "2026-01-01T00:00:00Z"},
            "statistics": {"viewCount": "5000", "likeCount": "200", "commentCount": "30"},
        }]
    }
    with patch.object(client._http, "get") as mock_get:
        mock_get.side_effect = [
            MagicMock(status_code=200, json=lambda: mock_search, raise_for_status=lambda: None),
            MagicMock(status_code=200, json=lambda: mock_details, raise_for_status=lambda: None),
        ]
        videos = client.get_videos()
    assert len(videos) == 1
    assert videos[0]["external_id"] == "vid123"
    assert videos[0]["platform"] == "youtube"

def test_get_metrics_from_video_list(client):
    videos = [{
        "external_id": "vid123",
        "views": 5000,
        "likes": 200,
        "comments": 30,
    }]
    metrics = client.extract_metrics(videos)
    assert metrics["vid123"]["views"] == 5000
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_sync_youtube.py -v
```
Expected: FAIL with import error

**Step 3: Implement orbit/platforms/youtube.py**

```python
import httpx

BASE_URL = "https://www.googleapis.com/youtube/v3"

class YouTubeClient:
    def __init__(self, api_key: str, channel_id: str):
        if not api_key:
            raise ValueError("YouTube api_key is required")
        self.channel_id = channel_id
        self._http = httpx.Client(timeout=30)
        self._key = api_key

    def get_videos(self, max_results: int = 50) -> list[dict]:
        search_resp = self._http.get(
            f"{BASE_URL}/search",
            params={
                "key": self._key,
                "channelId": self.channel_id,
                "part": "id",
                "order": "date",
                "maxResults": max_results,
                "type": "video",
            },
        )
        search_resp.raise_for_status()
        video_ids = [
            item["id"]["videoId"]
            for item in search_resp.json().get("items", [])
        ]
        if not video_ids:
            return []

        details_resp = self._http.get(
            f"{BASE_URL}/videos",
            params={
                "key": self._key,
                "id": ",".join(video_ids),
                "part": "snippet,statistics",
            },
        )
        details_resp.raise_for_status()

        videos = []
        for item in details_resp.json().get("items", []):
            stats = item.get("statistics", {})
            videos.append({
                "external_id": item["id"],
                "platform": "youtube",
                "content": item["snippet"]["title"],
                "published_at": item["snippet"]["publishedAt"],
                "views": int(stats.get("viewCount", 0)),
                "likes": int(stats.get("likeCount", 0)),
                "comments": int(stats.get("commentCount", 0)),
                "shares": 0,
                "reposts": 0,
                "clicks": 0,
                "saves": 0,
            })
        return videos

    def extract_metrics(self, videos: list[dict]) -> dict[str, dict]:
        return {
            v["external_id"]: {
                "views": v.get("views", 0),
                "likes": v.get("likes", 0),
                "comments": v.get("comments", 0),
                "shares": v.get("shares", 0),
                "reposts": v.get("reposts", 0),
                "clicks": v.get("clicks", 0),
                "saves": v.get("saves", 0),
            }
            for v in videos
        }
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_sync_youtube.py -v
```
Expected: 3 PASSED

**Step 5: Commit**

```bash
git add orbit/platforms/youtube.py tests/test_sync_youtube.py
git commit -m "feat: add YouTube API client for videos and metrics"
```

---

### Task 7: orbit sync Command

**Files:**
- Create: `orbit/commands/sync.py`

**Step 1: Implement orbit/commands/sync.py**

No unit test needed here — this is a thin orchestration layer wiring together already-tested modules. Tested manually in step 3.

```python
import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from orbit.config import Config
from orbit.db import DB
from orbit.patterns import PatternStore
from orbit.platforms.linkedin import LinkedInClient
from orbit.platforms.youtube import YouTubeClient

app = typer.Typer(help="Pull metrics from connected platforms")
console = Console()

PLATFORMS = ["linkedin", "youtube", "threads", "facebook"]

@app.callback(invoke_without_command=True)
def sync(
    platform: Optional[str] = typer.Option(None, "--platform", "-p", help="Sync one platform only"),
):
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
                progress.update(task, description=f"[green]✓ {target} synced[/green]", completed=True)
            except Exception as e:
                progress.update(task, description=f"[red]✗ {target} failed: {e}[/red]", completed=True)

    console.print("\n[bold green]Sync complete.[/bold green] Run [cyan]orbit insights[/cyan] to see what changed.")


def _sync_linkedin(cfg: Config, db: DB, ps: PatternStore, now: str):
    token = cfg.get("linkedin.access_token")
    author_urn = cfg.get("linkedin.author_urn")
    if not token or not author_urn:
        raise ValueError("LinkedIn not configured. Run: orbit setup --platform linkedin")

    client = LinkedInClient(access_token=token)
    posts = client.get_posts(author_urn=author_urn)

    for post in posts:
        existing = list(db.conn["posts"].rows_where("external_id = ?", [post["external_id"]]))
        if not existing:
            idea_id = db.conn["ideas"].insert({"title": post["content"][:100], "source": "sync", "status": "published", "created_at": post["published_at"]}).last_pk
            draft_id = db.conn["drafts"].insert({"idea_id": idea_id, "platform": "linkedin", "content": post["content"], "status": "published", "created_at": post["published_at"]}).last_pk
            db.conn["posts"].insert({"draft_id": draft_id, "platform": "linkedin", "external_id": post["external_id"], "published_at": post["published_at"]})

    all_posts = list(db.conn["posts"].rows_where("platform = ?", ["linkedin"]))
    urns = [p["external_id"] for p in all_posts if p["external_id"]]
    if urns:
        metrics_map = client.get_metrics(urns)
        for post_row in all_posts:
            m = metrics_map.get(post_row["external_id"])
            if m:
                db.conn["metrics"].insert({**m, "post_id": post_row["id"], "platform": "linkedin", "pulled_at": now})

    ps.recalculate("linkedin", db)


def _sync_youtube(cfg: Config, db: DB, ps: PatternStore, now: str):
    api_key = cfg.get("youtube.api_key")
    channel_id = cfg.get("youtube.channel_id")
    if not api_key or not channel_id:
        raise ValueError("YouTube not configured. Run: orbit setup --platform youtube")

    client = YouTubeClient(api_key=api_key, channel_id=channel_id)
    videos = client.get_videos()

    for video in videos:
        existing = list(db.conn["posts"].rows_where("external_id = ?", [video["external_id"]]))
        if not existing:
            idea_id = db.conn["ideas"].insert({"title": video["content"], "source": "sync", "status": "published", "created_at": video["published_at"]}).last_pk
            draft_id = db.conn["drafts"].insert({"idea_id": idea_id, "platform": "youtube", "content": video["content"], "status": "published", "created_at": video["published_at"]}).last_pk
            db.conn["posts"].insert({"draft_id": draft_id, "platform": "youtube", "external_id": video["external_id"], "published_at": video["published_at"]})

    all_posts = list(db.conn["posts"].rows_where("platform = ?", ["youtube"]))
    metrics_map = client.extract_metrics(videos)
    for post_row in all_posts:
        m = metrics_map.get(post_row["external_id"])
        if m:
            db.conn["metrics"].insert({**m, "post_id": post_row["id"], "platform": "youtube", "pulled_at": now})

    ps.recalculate("youtube", db)
```

**Step 2: Run manually to verify structure**

```bash
orbit sync --help
```
Expected: Shows `--platform` option and help text.

**Step 3: Commit**

```bash
git add orbit/commands/sync.py
git commit -m "feat: add orbit sync command for LinkedIn and YouTube"
```

---

### Task 8: orbit setup Command

**Files:**
- Create: `orbit/commands/setup.py`

**Step 1: Implement orbit/commands/setup.py**

```python
import typer
import webbrowser
from rich.console import Console
from rich.prompt import Prompt, Confirm
from orbit.config import Config

app = typer.Typer(help="Connect your platforms")
console = Console()

PLATFORMS = ["LinkedIn", "YouTube", "Threads", "Facebook", "Substack"]

@app.callback(invoke_without_command=True)
def setup(
    platform: str = typer.Option(None, "--platform", "-p", help="Re-configure one platform"),
):
    cfg = Config()

    if platform:
        _setup_platform(cfg, platform.lower())
        return

    console.print("\n[bold]Welcome to Orbit.[/bold] Let's connect your platforms.\n")

    choices = []
    for p in PLATFORMS:
        if Confirm.ask(f"  Connect [cyan]{p}[/cyan]?", default=True):
            choices.append(p.lower())

    console.print()
    for p in choices:
        _setup_platform(cfg, p)

    console.print("\n[bold green]Setup complete.[/bold green] Run [cyan]orbit sync[/cyan] to pull your existing post history.\n")


def _setup_platform(cfg: Config, platform: str):
    console.print(f"\n[bold cyan][{platform.upper()}][/bold cyan]")

    if platform == "linkedin":
        console.print("You need a LinkedIn app with r_liteprofile and w_member_social scopes.")
        console.print("Create one at: https://www.linkedin.com/developers/apps")
        client_id = Prompt.ask("  Client ID")
        client_secret = Prompt.ask("  Client Secret", password=True)
        token = Prompt.ask("  Access Token (from OAuth flow)")
        author_urn = Prompt.ask("  Author URN (e.g. urn:li:person:abc123)")
        cfg.set("linkedin.client_id", client_id)
        cfg.set("linkedin.client_secret", client_secret)
        cfg.set("linkedin.access_token", token)
        cfg.set("linkedin.author_urn", author_urn)
        console.print("  [green]✓ LinkedIn configured[/green]")

    elif platform == "youtube":
        console.print("You need a YouTube Data API v3 key from Google Cloud Console.")
        console.print("Create one at: https://console.cloud.google.com/apis/credentials")
        api_key = Prompt.ask("  API Key", password=True)
        channel_id = Prompt.ask("  Channel ID (e.g. UCxxxxxxxxxxxxxxxx)")
        cfg.set("youtube.api_key", api_key)
        cfg.set("youtube.channel_id", channel_id)
        console.print("  [green]✓ YouTube configured[/green]")

    elif platform in ("threads", "facebook"):
        console.print("Threads and Facebook use the Meta Graph API.")
        console.print("Create an app at: https://developers.facebook.com/apps")
        token = Prompt.ask("  Access Token")
        user_id = Prompt.ask("  User/Page ID")
        cfg.set(f"{platform}.access_token", token)
        cfg.set(f"{platform}.user_id", user_id)
        console.print(f"  [green]✓ {platform.title()} configured[/green]")

    elif platform == "substack":
        console.print("Substack has no public API. Orbit will draft content for manual publish.")
        pub_url = Prompt.ask("  Your publication URL (e.g. https://yourname.substack.com)")
        cfg.set("substack.publication_url", pub_url)
        console.print("  [green]✓ Substack configured (manual publish mode)[/green]")

    else:
        console.print(f"  [yellow]Unknown platform: {platform}[/yellow]")
```

**Step 2: Verify command loads**

```bash
orbit setup --help
```
Expected: Shows `--platform` option and help text.

**Step 3: Commit**

```bash
git add orbit/commands/setup.py
git commit -m "feat: add orbit setup wizard for platform configuration"
```

---

### Task 9: Full Test Suite + README

**Step 1: Run full test suite**

```bash
pytest tests/ -v
```
Expected: All tests pass. Note total count.

**Step 2: Verify CLI end-to-end**

```bash
orbit --help
orbit setup --help
orbit sync --help
```
All three should show clean help output.

**Step 3: Add pytest to dev dependencies in pyproject.toml**

Add under `[project]`:
```toml
[project.optional-dependencies]
dev = ["pytest>=8", "pytest-mock>=3"]
```

Reinstall:
```bash
pip install -e ".[dev]"
```

**Step 4: Final commit**

```bash
git add pyproject.toml
git commit -m "feat: add dev dependencies, complete Phase 1 foundation"
```

---

## Phase 1 Complete

At the end of Phase 1 you have:
- `orbit setup` — connects LinkedIn, YouTube, Threads, Facebook, Substack
- `orbit sync` — pulls post history + metrics from LinkedIn and YouTube, writes pattern files
- SQLite database fully schemed and migrated
- Pattern files auto-generated from real data
- Full test coverage on all data/API layers

**Next: Phase 2** — `orbit idea` (add/list/suggest) + `orbit draft` with Claude integration
