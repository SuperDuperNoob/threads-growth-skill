from datetime import datetime, timezone
from pathlib import Path

from orbit.db import DB
from orbit.reports import (
    find_repo_root,
    render_winning_formats,
    write_winning_formats_for_threads,
)


def _seed_threads_post(db: DB, *, title: str, views: int, likes: int, comments: int, ext_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    idea_id = db.conn["ideas"].insert({
        "title": title[:100], "source": "sync", "status": "published", "created_at": now,
    }).last_pk
    draft_id = db.conn["drafts"].insert({
        "idea_id": idea_id, "platform": "threads", "content": title,
        "status": "published", "created_at": now,
    }).last_pk
    post_id = db.conn["posts"].insert({
        "draft_id": draft_id, "platform": "threads",
        "external_id": ext_id, "published_at": now,
    }).last_pk
    db.conn["metrics"].insert({
        "post_id": post_id, "platform": "threads",
        "views": views, "likes": likes, "comments": comments,
        "shares": 0, "reposts": 0, "clicks": 0, "saves": 0,
        "pulled_at": now,
    })


def test_render_handles_empty_data():
    out = render_winning_formats([])
    assert "No synced data yet" in out


def test_render_includes_totals_and_top_table():
    data = [
        {"title": "有人剛剛開源了排程平台", "published_at": "2026-05-01", "views": 60000, "likes": 900, "comments": 30, "like_rate": 1.5},
        {"title": "Anthropic 的 Frontend Design skill 上線", "published_at": "2026-05-02", "views": 44000, "likes": 880, "comments": 30, "like_rate": 2.0},
        {"title": "你的 AI agent 為什麼爬不了大部分網站？", "published_at": "2026-05-03", "views": 10000, "likes": 160, "comments": 15, "like_rate": 1.6},
    ]
    out = render_winning_formats(data)
    assert "Total views: **114,000**" in out
    assert "Anthropic" in out
    assert "Hook Template Performance" in out
    assert "a (Someone-verb)" in out
    assert "b (Brand-verb)" in out
    assert "d (Question)" in out


def test_write_winning_formats_skipped_when_no_repo_root(tmp_path, monkeypatch):
    # cwd is a plain tmp dir with no SKILL.md → find_repo_root returns None,
    # writer returns None instead of scribbling files.
    monkeypatch.chdir(tmp_path)
    db = DB(home=tmp_path / ".orbit")
    assert write_winning_formats_for_threads(db) is None


def test_write_winning_formats_writes_into_skill_checkout(tmp_path):
    # Simulate a skill checkout: SKILL.md + references/ at the root.
    root = tmp_path / "skill"
    (root / "references").mkdir(parents=True)
    (root / "SKILL.md").write_text("# test skill\n")

    db = DB(home=tmp_path / ".orbit")
    _seed_threads_post(db, title="有人剛剛開源了 X", views=50000, likes=750, comments=20, ext_id="t1")
    _seed_threads_post(db, title="Anthropic 上線了 Y", views=40000, likes=800, comments=10, ext_id="t2")

    out = write_winning_formats_for_threads(db, repo_root=root)
    assert out == root / "references" / "winning-formats.md"
    body = out.read_text()
    assert "Total views: **90,000**" in body
    assert "Anthropic" in body


def test_find_repo_root_walks_up(tmp_path, monkeypatch):
    root = tmp_path / "skill"
    (root / "references").mkdir(parents=True)
    (root / "SKILL.md").write_text("# test\n")
    deep = root / "orbit" / "commands"
    deep.mkdir(parents=True)
    monkeypatch.chdir(deep)
    assert find_repo_root() == root.resolve()
