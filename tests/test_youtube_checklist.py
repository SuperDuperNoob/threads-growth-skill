"""Tests for the YouTube checklist schema, seeding, and blocks_next enforcement.

We don't go through Typer here — we exercise the underlying DB + template
directly so the tests don't depend on the CLI runner being available.
"""
from datetime import datetime, timezone

import pytest

from orbit.db import DB
from orbit.youtube_checklist_template import TEMPLATE, TemplateItem


# ---- schema ----


def test_youtube_tables_created(orbit_home):
    db = DB(orbit_home)
    tables = db.conn.table_names()
    assert "youtube_checklists" in tables
    assert "youtube_checklist_items" in tables


def test_youtube_checklist_columns(orbit_home):
    db = DB(orbit_home)
    cols = {c.name for c in db.conn["youtube_checklist_items"].columns}
    for required in (
        "checklist_id", "phase", "order_idx", "label", "detail",
        "blocks_next", "completed_at", "notes",
    ):
        assert required in cols, f"missing column {required!r}"


# ---- template ----


def test_template_has_all_four_phases():
    phases = {item.phase for item in TEMPLATE}
    assert phases == {"pre-production", "scripting", "filming", "post-production"}


def test_template_has_at_least_one_blocker_per_blocking_phase():
    """Pre-prod, scripting, and post-prod each have a 'must lock before moving on'
    item. Filming is allowed to be free-flowing."""
    blockers_by_phase: dict[str, list[TemplateItem]] = {}
    for item in TEMPLATE:
        if item.blocks_next:
            blockers_by_phase.setdefault(item.phase, []).append(item)
    assert "pre-production" in blockers_by_phase
    assert "scripting" in blockers_by_phase
    assert "post-production" in blockers_by_phase


def test_template_includes_jeff_hook_framework():
    """The hook framework from the Jeff Sue interview must be findable in some
    item's detail field — this is the load-bearing part of the template."""
    found = any(
        "Confirm to the viewer they clicked" in (item.detail or "")
        for item in TEMPLATE
    )
    assert found, "Jeff's 3-part hook framework went missing from the template"


def test_template_includes_55_char_title_rule():
    """Keith's A/B title rule — each title must be ≤55 chars and use different
    hook angles. Reading this from the template confirms it survived edits."""
    found = any(
        "55 char" in (item.detail or "").lower() or "≤55" in (item.detail or "")
        for item in TEMPLATE
    )
    assert found, "55-char title rule went missing from the template"


# ---- seeding + blocks_next behavior ----


def _seed_one(db: DB, title: str = "Test video") -> int:
    """Seed a new checklist with TEMPLATE, return the checklist id.
    Mirrors what `orbit youtube new` does, minus the Rich output."""
    now = datetime.now(timezone.utc).isoformat()
    cid = db.conn["youtube_checklists"].insert({
        "title": title, "status": "in_progress", "created_at": now,
    }).last_pk
    for i, item in enumerate(TEMPLATE):
        db.conn["youtube_checklist_items"].insert({
            "checklist_id": cid,
            "phase": item.phase,
            "order_idx": i,
            "label": item.label,
            "detail": item.detail,
            "blocks_next": 1 if item.blocks_next else 0,
        })
    return cid


def test_seeding_creates_all_items(orbit_home):
    db = DB(orbit_home)
    cid = _seed_one(db)
    n = list(db.conn.query(
        "SELECT COUNT(*) AS n FROM youtube_checklist_items WHERE checklist_id = ?",
        [cid],
    ))[0]["n"]
    assert n == len(TEMPLATE)


def test_seeding_preserves_order(orbit_home):
    db = DB(orbit_home)
    cid = _seed_one(db)
    rows = list(db.conn.query(
        "SELECT order_idx, label FROM youtube_checklist_items "
        "WHERE checklist_id = ? ORDER BY order_idx",
        [cid],
    ))
    assert rows[0]["label"] == TEMPLATE[0].label
    assert rows[-1]["label"] == TEMPLATE[-1].label


def test_blocks_next_query_finds_open_upstream_blockers(orbit_home):
    """Replicates the query in `orbit youtube check`: for a given item, find any
    upstream item with blocks_next=1 that hasn't been completed."""
    db = DB(orbit_home)
    cid = _seed_one(db)

    # Find the first item marked blocks_next, and the first item AFTER it
    items = list(db.conn.query(
        "SELECT id, order_idx, blocks_next FROM youtube_checklist_items "
        "WHERE checklist_id = ? ORDER BY order_idx",
        [cid],
    ))
    blocker = next(i for i in items if i["blocks_next"])
    after = next(i for i in items if i["order_idx"] > blocker["order_idx"])

    # No completion yet → blocker should be open for any downstream item
    open_blockers = list(db.conn.query(
        "SELECT id FROM youtube_checklist_items "
        "WHERE checklist_id = ? AND order_idx < ? "
        "AND blocks_next = 1 AND completed_at IS NULL",
        [cid, after["order_idx"]],
    ))
    assert any(b["id"] == blocker["id"] for b in open_blockers)

    # Mark the blocker complete → it should drop out of open_blockers
    db.conn["youtube_checklist_items"].update(blocker["id"], {
        "completed_at": datetime.now(timezone.utc).isoformat(),
    })
    open_blockers = list(db.conn.query(
        "SELECT id FROM youtube_checklist_items "
        "WHERE checklist_id = ? AND order_idx < ? "
        "AND blocks_next = 1 AND completed_at IS NULL",
        [cid, after["order_idx"]],
    ))
    assert all(b["id"] != blocker["id"] for b in open_blockers)


def test_progress_counts_done_vs_total(orbit_home):
    db = DB(orbit_home)
    cid = _seed_one(db)
    # Mark first three done
    first_three = list(db.conn.query(
        "SELECT id FROM youtube_checklist_items WHERE checklist_id = ? "
        "ORDER BY order_idx LIMIT 3",
        [cid],
    ))
    for r in first_three:
        db.conn["youtube_checklist_items"].update(r["id"], {
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
    stats = list(db.conn.query(
        "SELECT COUNT(*) AS total, "
        "       SUM(CASE WHEN completed_at IS NOT NULL THEN 1 ELSE 0 END) AS done "
        "FROM youtube_checklist_items WHERE checklist_id = ?",
        [cid],
    ))[0]
    assert stats["done"] == 3
    assert stats["total"] == len(TEMPLATE)
