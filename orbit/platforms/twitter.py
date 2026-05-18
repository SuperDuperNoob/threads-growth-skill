from __future__ import annotations
import json
import time
import re
from pathlib import Path
from typing import Any
import httpx

CACHE_TTL = 3600  # 1 hour


class BookmarkCache:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> list[dict] | None:
        if not self._path.exists():
            return None
        try:
            data = json.loads(self._path.read_text())
        except json.JSONDecodeError:
            return None
        if time.time() - data.get("ts", 0) > CACHE_TTL:
            return None
        return data.get("items")

    def save(self, items: list[dict]) -> None:
        self._path.write_text(json.dumps({"ts": time.time(), "items": items}))


class TwitterClient:
    def __init__(self, cookies_path: str | None) -> None:
        if not cookies_path:
            raise ValueError("cookies_path is required")
        self._cookies_path = Path(cookies_path).expanduser()

    def _load_cookies(self) -> dict[str, str]:
        cookies: dict[str, str] = {}
        if not self._cookies_path.exists():
            raise FileNotFoundError(f"Cookie file not found: {self._cookies_path}")
        for line in self._cookies_path.read_text().splitlines():
            if line.startswith("#") or not line.strip():
                continue
            parts = line.strip().split("\t")
            if len(parts) >= 7:
                name, value = parts[5], parts[6]
                cookies[name] = value
        for required in ("ct0", "auth_token"):
            if required not in cookies:
                raise ValueError(
                    f"Cookie '{required}' not found in {self._cookies_path}. "
                    "Export fresh cookies from your browser and re-run: orbit setup --platform twitter"
                )
        return cookies

    def get_bookmarks(self, limit: int = 50) -> list[dict[str, Any]]:
        cookies = self._load_cookies()
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "x-twitter-active-user": "yes",
            "x-twitter-auth-type": "OAuth2Session",
            "x-csrf-token": cookies.get("ct0", ""),
            "Referer": "https://x.com/i/bookmarks",
        }
        variables = json.dumps({
            "count": limit,
            "includePromotedContent": False,
        })
        features = json.dumps({
            "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
            "view_counts_everywhere_api_enabled": True,
            "longform_notetweets_consumption_enabled": True,
            "tweet_awards_web_tipping_enabled": False,
            "freedom_of_speech_not_reach_fetch_enabled": True,
            "standardized_nudges_misinfo": True,
            "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": False,
            "interactive_text_enabled": True,
            "responsive_web_text_conversations_enabled": False,
            "longform_notetweets_richtext_consumption_enabled": True,
            "responsive_web_enhance_cards_enabled": False,
        })
        resp = httpx.get(
            "https://x.com/i/api/graphql/tmd4G22LV4y1pTu6R0YQRA/Bookmarks",
            params={"variables": variables, "features": features},
            headers=headers,
            cookies=cookies,
            timeout=30,
        )
        resp.raise_for_status()
        return self._parse_bookmarks(resp.json())

    def _parse_bookmarks(self, data: dict) -> list[dict[str, Any]]:
        results = []
        try:
            entries = (
                data["data"]["bookmark_timeline_v2"]["timeline"]["instructions"][0]["entries"]
            )
        except (KeyError, IndexError):
            return results
        for entry in entries:
            try:
                tweet = entry["content"]["itemContent"]["tweet_results"]["result"]
                legacy = tweet.get("legacy", tweet.get("tweet", {}).get("legacy", {}))
                user = (
                    tweet.get("core", {})
                    .get("user_results", {})
                    .get("result", {})
                    .get("legacy", {})
                )
                text = legacy.get("full_text", "")
                text = re.sub(r"https://t\.co/\S+", "", text).strip()
                tweet_id = legacy.get("id_str", "")
                screen_name = user.get("screen_name", "unknown")
                results.append({
                    "text": text,
                    "author": f"@{screen_name}",
                    "url": f"https://x.com/{screen_name}/status/{tweet_id}",
                })
            except (KeyError, TypeError):
                continue
        return results
