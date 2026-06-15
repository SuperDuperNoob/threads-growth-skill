"""ORBIT_HOME env var resolution.

Both DB and Config must honor $ORBIT_HOME so Hermes (on the Beelink) and Keith's
Mac can point at the same NAS-hosted ~/.orbit. Explicit home= arg always wins;
then $ORBIT_HOME; then ~/.orbit.
"""
from __future__ import annotations
from pathlib import Path

from orbit.paths import resolve_orbit_home
from orbit.db import DB
from orbit.config import Config


def test_resolve_prefers_explicit_arg(tmp_path, monkeypatch):
    monkeypatch.setenv("ORBIT_HOME", str(tmp_path / "env"))
    explicit = tmp_path / "explicit"
    assert resolve_orbit_home(explicit) == explicit


def test_resolve_uses_env_when_no_arg(tmp_path, monkeypatch):
    monkeypatch.setenv("ORBIT_HOME", str(tmp_path / "env"))
    assert resolve_orbit_home(None) == tmp_path / "env"


def test_resolve_falls_back_to_home(tmp_path, monkeypatch):
    monkeypatch.delenv("ORBIT_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert resolve_orbit_home(None) == tmp_path / ".orbit"


def test_db_honors_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ORBIT_HOME", str(tmp_path / "nas"))
    db = DB()
    assert (tmp_path / "nas" / "orbit.db").exists()


def test_config_honors_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ORBIT_HOME", str(tmp_path / "nas"))
    cfg = Config()
    assert cfg.home == tmp_path / "nas"
    assert (tmp_path / "nas" / "config.json").exists()


def test_explicit_arg_still_overrides_env_for_db(tmp_path, monkeypatch):
    monkeypatch.setenv("ORBIT_HOME", str(tmp_path / "env"))
    DB(home=tmp_path / "explicit")
    assert (tmp_path / "explicit" / "orbit.db").exists()
    assert not (tmp_path / "env").exists()
