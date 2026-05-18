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

def test_load_cookies_raises_on_missing_ct0(tmp_path):
    cookies_file = tmp_path / "cookies.txt"
    # Valid netscape format but missing ct0 and auth_token
    cookies_file.write_text("# Netscape HTTP Cookie File\n.x.com\tTRUE\t/\tTRUE\t0\tother_cookie\tvalue\n")
    client = TwitterClient(cookies_path=str(cookies_file))
    with pytest.raises(ValueError, match="ct0"):
        client._load_cookies()

def test_get_bookmarks_makes_http_call(tmp_path):
    cookies_file = tmp_path / "cookies.txt"
    # Valid cookies with required fields
    cookies_file.write_text(
        "# Netscape HTTP Cookie File\n"
        ".x.com\tTRUE\t/\tTRUE\t0\tct0\tfaketoken\n"
        ".x.com\tTRUE\t/\tTRUE\t0\tauth_token\tfakeauth\n"
    )
    client = TwitterClient(cookies_path=str(cookies_file))
    mock_response = MagicMock()
    mock_response.json.return_value = {"data": {"bookmark_timeline_v2": {"timeline": {"instructions": []}}}}
    mock_response.raise_for_status = MagicMock()
    with patch("orbit.platforms.twitter.httpx.get", return_value=mock_response) as mock_get:
        result = client.get_bookmarks(limit=10)
    mock_get.assert_called_once()
    assert result == []

def test_bookmark_cache_load_handles_corrupt_json(tmp_path):
    cache = BookmarkCache(tmp_path / "cache.json")
    (tmp_path / "cache.json").write_text("not valid json{{{")
    assert cache.load() is None
