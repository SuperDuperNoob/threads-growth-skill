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

def test_migrate_is_idempotent(orbit_home):
    DB(orbit_home)
    db2 = DB(orbit_home)
    tables = db2.conn.table_names()
    assert "ideas" in tables
    assert "drafts" in tables

def test_not_null_constraint_enforced(orbit_home):
    import sqlite3
    db = DB(orbit_home)
    with pytest.raises(Exception):  # sqlite3.IntegrityError or sqlite_utils equivalent
        db.conn["ideas"].insert({"source": "user", "status": "pending"})  # missing title
