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
