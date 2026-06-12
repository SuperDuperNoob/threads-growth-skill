import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from orbit.platforms.twitter import (
    TwitterClient,
    BookmarkCache,
    _parse_netscape_cookies,
    _extract_source_links,
)
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
    with pytest.raises(ValueError, match="ct0"):
        _parse_netscape_cookies(cookies_file)

def test_parse_netscape_cookies_returns_dict(tmp_path):
    cookies_file = tmp_path / "cookies.txt"
    cookies_file.write_text(
        "# Netscape HTTP Cookie File\n"
        ".x.com\tTRUE\t/\tTRUE\t0\tct0\tfaketoken\n"
        ".x.com\tTRUE\t/\tTRUE\t0\tauth_token\tfakeauth\n"
    )
    cookies = _parse_netscape_cookies(cookies_file)
    assert cookies["ct0"] == "faketoken"
    assert cookies["auth_token"] == "fakeauth"

def test_bookmark_cache_load_handles_corrupt_json(tmp_path):
    cache = BookmarkCache(tmp_path / "cache.json")
    (tmp_path / "cache.json").write_text("not valid json{{{")
    assert cache.load() is None


# Regression: drafts 913–915 had empty source_links because the GitHub URL
# lived in note_tweet (long-tweet body), not legacy.entities.urls. The
# extractor must also look in note_tweet and quoted_status.

def test_extract_source_links_from_legacy_entities():
    tweet = {
        "legacy": {
            "entities": {
                "urls": [
                    {"expanded_url": "https://github.com/org/repo"},
                    {"expanded_url": "https://example.com/post"},
                ]
            }
        }
    }
    assert _extract_source_links(tweet) == [
        "https://github.com/org/repo",
        "https://example.com/post",
    ]


def test_extract_source_links_from_note_tweet():
    """Long tweets store URLs in note_tweet.note_tweet_results.result.entity_set.urls."""
    tweet = {
        "legacy": {"entities": {"urls": []}},
        "note_tweet": {
            "note_tweet_results": {
                "result": {
                    "entity_set": {
                        "urls": [
                            {"expanded_url": "https://github.com/microsoft/skillopt"}
                        ]
                    }
                }
            }
        },
    }
    assert _extract_source_links(tweet) == ["https://github.com/microsoft/skillopt"]


def test_extract_source_links_from_quoted_tweet():
    """When a bookmark quote-tweets a project, the URL is in the quoted tweet."""
    tweet = {
        "legacy": {"entities": {"urls": []}},
        "quoted_status_result": {
            "result": {
                "legacy": {
                    "entities": {
                        "urls": [
                            {"expanded_url": "https://github.com/llamaindex/liteparse"}
                        ]
                    }
                }
            }
        },
    }
    assert _extract_source_links(tweet) == [
        "https://github.com/llamaindex/liteparse"
    ]


def test_extract_source_links_dedupes_across_sources():
    """A URL that appears in both legacy and note_tweet should appear once."""
    tweet = {
        "legacy": {
            "entities": {
                "urls": [{"expanded_url": "https://github.com/org/repo"}]
            }
        },
        "note_tweet": {
            "note_tweet_results": {
                "result": {
                    "entity_set": {
                        "urls": [{"expanded_url": "https://github.com/org/repo"}]
                    }
                }
            }
        },
    }
    assert _extract_source_links(tweet) == ["https://github.com/org/repo"]


def test_extract_source_links_missing_sections_returns_empty():
    """Tweet with no URL entities anywhere returns [] without raising."""
    assert _extract_source_links({"legacy": {}}) == []
    assert _extract_source_links({}) == []
