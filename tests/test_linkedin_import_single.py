"""Tests for `orbit linkedin import single` — SinglePostAnalytics_*.xlsx ingest.

This export is a key-value sheet ('Post analytics'): label in col A, value in col B,
with a 3-col demographics block lower down. It carries the real reaction/comment/
repost/save breakdown the API can't return on personal authors.

Mapping (locked with Keith 2026-06-15):
  views=Impressions, likes=Reactions, comments=Comments,
  reposts=Reposts, shares=Reposts (mirror), saves=Saves, clicks=0.

Dedupe key is the IN-URL urn (…-share-<urn>-…), NOT the filename urn — they differ.
"""
from __future__ import annotations
from pathlib import Path

import pytest
from openpyxl import Workbook

from orbit.commands.linkedin_import import parse_single_post_analytics, import_single
from orbit.db import DB


def _make_single_post_xlsx(
    path: Path,
    *,
    post_url: str,
    post_date: str = "5/29/2026",
    impressions: int = 521,
    reach: int = 343,
    reactions: int = 7,
    comments: int = 3,
    reposts: int = 0,
    saves: int = 1,
    social_engagements: int = 11,
) -> Path:
    """Build a minimal SinglePostAnalytics-shaped workbook for tests."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Post analytics"
    rows = [
        ("Post URL", post_url),
        ("Post Date", post_date),
        ("Post Publish Time", "9:00 AM"),
        (None, None),
        ("Post Performance", None),
        ("Impressions", impressions),
        ("Members reached", reach),
        ("Profile activity", None),
        ("Profile viewers from this post", 7),
        ("Followers gained from this post", 0),
        ("Engagement", None),
        ("Social engagements", social_engagements),
        ("Reactions", reactions),
        ("Comments", comments),
        ("Reposts", reposts),
        ("Saves", saves),
        ("Sends on LinkedIn", 0),
        ("Link engagements", 0),
        (None, None),
        ("Post viewer demographics", None),
        ("Category", "Value", "%"),
        ("Job title", "Founder", "7%"),  # 3-col row must NOT be read as a metric
    ]
    for r in rows:
        ws.append(r)
    wb.save(path)
    return path


URL = (
    "https://www.linkedin.com/posts/rumjahn_my-wife-finally-stopped-asking-"
    "share-7465929965994156033-D7aZ"
)


# --- pure parser ---


def test_parse_extracts_in_url_urn(tmp_path):
    f = _make_single_post_xlsx(tmp_path / "p.xlsx", post_url=URL)
    parsed = parse_single_post_analytics(f)
    # Must be the in-URL urn, not anything from the filename.
    assert parsed["urn"] == "7465929965994156033"


def test_parse_maps_metrics(tmp_path):
    f = _make_single_post_xlsx(
        tmp_path / "p.xlsx", post_url=URL,
        impressions=2856, reactions=12, comments=8, reposts=1, saves=1,
    )
    p = parse_single_post_analytics(f)
    assert p["views"] == 2856
    assert p["likes"] == 12       # Reactions -> likes
    assert p["comments"] == 8
    assert p["reposts"] == 1
    assert p["shares"] == 1       # mirror of reposts (locked mapping)
    assert p["saves"] == 1
    assert p["clicks"] == 0


def test_parse_date_to_iso(tmp_path):
    f = _make_single_post_xlsx(tmp_path / "p.xlsx", post_url=URL, post_date="6/13/2026")
    p = parse_single_post_analytics(f)
    assert p["published_at"].startswith("2026-06-13")


def test_parse_ignores_three_col_demographic_rows(tmp_path):
    # Reactions etc. are 2-col rows; 'Job title|Founder|7%' is a 3-col row.
    # A naive parser could mistake demographic rows for metrics. Guard it.
    f = _make_single_post_xlsx(tmp_path / "p.xlsx", post_url=URL, reactions=7)
    p = parse_single_post_analytics(f)
    assert p["likes"] == 7  # not clobbered by 'Job title' rows


# --- DB writer ---


def test_import_single_inserts_post_and_metrics(tmp_path, orbit_home):
    f = _make_single_post_xlsx(tmp_path / "p.xlsx", post_url=URL, impressions=521)
    db = DB(home=orbit_home)
    import_single([f], db=db)

    posts = list(db.conn["posts"].rows_where("external_id = ?", ["7465929965994156033"]))
    assert len(posts) == 1
    assert posts[0]["platform"] == "linkedin"

    metrics = list(db.conn["metrics"].rows_where("post_id = ?", [posts[0]["id"]]))
    assert len(metrics) == 1
    assert metrics[0]["views"] == 521


def test_import_single_is_idempotent_on_urn(tmp_path, orbit_home):
    # Re-importing the SAME post must not create a duplicate posts row.
    f = _make_single_post_xlsx(tmp_path / "p.xlsx", post_url=URL)
    db = DB(home=orbit_home)
    import_single([f], db=db)
    import_single([f], db=db)  # second run

    posts = list(db.conn["posts"].rows_where("external_id = ?", ["7465929965994156033"]))
    assert len(posts) == 1  # exactly one post, not two


def test_import_single_dedupes_against_existing_api_synced_post(tmp_path, orbit_home):
    """A post already synced via the API stores external_id as the in-URL urn.
    Importing its SinglePostAnalytics export must attach to that row, not fork a new one.
    """
    db = DB(home=orbit_home)
    # Simulate an API-synced post row keyed on the in-URL urn.
    idea_id = db.conn["ideas"].insert(
        {"title": "x", "source": "api", "status": "published", "created_at": "2026-05-29"}
    ).last_pk
    draft_id = db.conn["drafts"].insert(
        {"idea_id": idea_id, "platform": "linkedin", "content": "real text",
         "status": "published", "created_at": "2026-05-29"}
    ).last_pk
    db.conn["posts"].insert(
        {"draft_id": draft_id, "platform": "linkedin",
         "external_id": "7465929965994156033", "published_at": "2026-05-29"}
    )

    f = _make_single_post_xlsx(tmp_path / "p.xlsx", post_url=URL, impressions=999)
    import_single([f], db=db)

    posts = list(db.conn["posts"].rows_where("external_id = ?", ["7465929965994156033"]))
    assert len(posts) == 1  # attached to existing, no fork
    metrics = list(db.conn["metrics"].rows_where("post_id = ?", [posts[0]["id"]]))
    assert metrics[0]["views"] == 999
