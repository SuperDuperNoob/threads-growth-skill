import pytest
from unittest.mock import patch, MagicMock
from orbit.platforms.twitter import TwitterClient, BookmarkCache
from pathlib import Path
import json, time

def test_bookmark_cache_miss(tmp_path):
    cache = BookmarkCache(tmp_path / "cache.json")
    assert cache.load() is None

def test_bookmark_cache_hit(tmp_path):
    cache = BookmarkCache(tmp_path / "cache.json")
    items = [{"text": "hello", "url": "https://x.com/1", "author": "@test"}]
    cache.save(items)
    result = cache.load()
    assert result == items

def test_bookmark_cache_expired(tmp_path):
    cache = BookmarkCache(tmp_path / "cache.json")
    items = [{"text": "old", "url": "https://x.com/1", "author": "@test"}]
    cache.save(items)
    data = json.loads((tmp_path / "cache.json").read_text())
    data["ts"] = time.time() - 7200  # 2 hours ago
    (tmp_path / "cache.json").write_text(json.dumps(data))
    assert cache.load() is None  # expired

def test_client_requires_cookies():
    with pytest.raises(ValueError, match="cookies_path"):
        TwitterClient(cookies_path=None)
