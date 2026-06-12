from __future__ import annotations
import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

CACHE_TTL = 3600  # 1 hour

_BOOKMARKS_URL = "https://x.com/i/api/graphql/qToeLeMs43Q8cr7tRYXmaQ/Bookmarks"
# HomeTimeline = the "For You" feed (algorithmic). Hash from twikit 2.3.3.
_HOME_TIMELINE_URL = "https://x.com/i/api/graphql/-X_hcgQzmHGl29-UXxz4sw/HomeTimeline"
# Twitter's hardcoded Bearer token used by the web app
_BEARER = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D"
    "1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)


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


def _extract_media(legacy: dict) -> tuple[str | None, str | None]:
    """Pull the best media URL out of a tweet legacy block.

    Returns (url, type) where type is one of 'video', 'animated_gif', 'photo'.
    For video/gif, picks the highest-bitrate mp4 variant. For photos, returns the first.
    """
    media_list = (legacy.get("extended_entities") or {}).get("media") or legacy.get("entities", {}).get("media") or []
    if not media_list:
        return None, None
    first = media_list[0]
    mtype = first.get("type")  # 'photo', 'video', 'animated_gif'
    if mtype in ("video", "animated_gif"):
        variants = (first.get("video_info") or {}).get("variants") or []
        mp4s = [v for v in variants if v.get("content_type") == "video/mp4" and v.get("url")]
        if not mp4s:
            return None, mtype
        # Highest bitrate wins
        best = max(mp4s, key=lambda v: v.get("bitrate", 0))
        return best["url"], mtype
    if mtype == "photo":
        return first.get("media_url_https") or first.get("media_url"), mtype
    return None, mtype


# GraphQL FEATURES dict, used by HomeTimeline and other timeline endpoints. Pulled
# from twikit 2.3.3 — kept in sync with what X's web client sends.
_GQL_FEATURES: dict[str, bool] = {
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "tweetypie_unmention_optimization_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "responsive_web_media_download_video_enabled": False,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
}


async def _init_transaction_id(http, user_agent: str, target_url: str, method: str = "GET") -> str:
    """Set up the X-Client-Transaction-Id with the same retry logic as bookmarks.
    Centralizing this means HomeTimeline gets the same anti-bot resilience for free."""
    from twikit.x_client_transaction import ClientTransaction

    ct_headers = {
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Referer": "https://x.com",
        "User-Agent": user_agent,
    }
    tx = ClientTransaction()
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            await tx.init(http, ct_headers)
            break
        except Exception as e:
            last_err = e
            if attempt < 2:
                await asyncio.sleep(1 << attempt)
    else:
        raise RuntimeError(
            "X anti-bot fingerprint failed after 3 attempts. "
            "This is usually transient — try again in a minute. "
            f"(last error: {last_err})"
        )
    return tx.generate_transaction_id(method=method, path=urlparse(target_url).path)


def _collect_entries(instructions: list[dict]) -> list[dict]:
    """Flatten all entries out of a timeline instructions list."""
    entries: list[dict] = []
    for inst in instructions:
        entries.extend(inst.get("entries", []))
    return entries


def _extract_source_links(tweet: dict) -> list[str]:
    """Collect expanded URLs from every place X stores them on a tweet.

    Long tweets put URL entities in `note_tweet.note_tweet_results.result.entity_set.urls`,
    not `legacy.entities.urls`. Quote-tweets keep their URLs on the quoted tweet.
    We merge all three so handoff can find a GitHub link wherever it lives.
    """
    seen: set[str] = set()
    out: list[str] = []

    def _absorb(url_entities: list | None) -> None:
        for u in url_entities or []:
            url = (u or {}).get("expanded_url")
            if url and url not in seen:
                seen.add(url)
                out.append(url)

    legacy = (tweet.get("legacy") or {})
    _absorb((legacy.get("entities") or {}).get("urls"))

    note = (
        ((tweet.get("note_tweet") or {})
         .get("note_tweet_results") or {})
        .get("result") or {}
    )
    _absorb((note.get("entity_set") or {}).get("urls"))

    quoted = (
        (tweet.get("quoted_status_result") or {})
        .get("result") or {}
    )
    quoted_legacy = quoted.get("legacy") or {}
    _absorb((quoted_legacy.get("entities") or {}).get("urls"))

    return out


def _parse_timeline_entries(entries: list[dict]) -> list[dict[str, Any]]:
    """Parse a list of timeline entries into our standard tweet dict shape.

    Works for both bookmark timeline and home timeline since both use the same
    `content.itemContent.tweet_results.result` shape per entry. Skips non-tweet
    entries (cursors, modules, ads) silently."""
    results: list[dict[str, Any]] = []
    for entry in entries:
        try:
            tweet = entry["content"]["itemContent"]["tweet_results"]["result"]
            legacy = tweet.get("legacy") or tweet.get("tweet", {}).get("legacy", {})
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
            if not text:
                continue
            media_url, media_type = _extract_media(legacy)
            # Capture expanded URLs from anywhere on the tweet — legacy entities,
            # note_tweet (long tweets store URLs here), and quoted_status. These
            # often include the GitHub repo / project homepage that the tweet
            # references; we use one as a threaded comment on handoff.
            source_links = _extract_source_links(tweet)
            results.append({
                "text": text,
                "media_url": media_url,
                "media_type": media_type,
                "author": f"@{screen_name}",
                "url": f"https://x.com/{screen_name}/status/{tweet_id}",
                "tweet_id": tweet_id,
                "source_links": source_links,
                "source_likes": int(legacy.get("favorite_count") or 0),
                "source_retweets": int(legacy.get("retweet_count") or 0),
                "source_views": int((tweet.get("views") or {}).get("count") or 0),
                "created_at": legacy.get("created_at"),
            })
        except (KeyError, TypeError):
            continue
    return results


def _parse_netscape_cookies(path: Path) -> dict[str, str]:
    """Parse Netscape cookies.txt format into a name→value dict."""
    cookies: dict[str, str] = {}
    if not path.exists():
        raise FileNotFoundError(f"Cookie file not found: {path}")
    for line in path.read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.strip().split("\t")
        if len(parts) >= 7:
            cookies[parts[5]] = parts[6]
    for required in ("ct0", "auth_token"):
        if required not in cookies:
            raise ValueError(
                f"Cookie '{required}' not found in {path}. "
                "Export fresh cookies from your browser and re-run: orbit setup --platform twitter"
            )
    return cookies


class TwitterClient:
    """Fetches X bookmarks. Uses twikit only to compute the anti-bot
    X-Client-Transaction-Id header; the actual GraphQL call and parsing
    are done here to avoid twikit's brittle Tweet/User schema."""

    def __init__(self, cookies_path: str | None) -> None:
        if not cookies_path:
            raise ValueError("cookies_path is required")
        self._cookies_path = Path(cookies_path).expanduser()

    def get_bookmarks(self, limit: int = 50) -> list[dict[str, Any]]:
        cookies = _parse_netscape_cookies(self._cookies_path)
        return asyncio.run(self._fetch(cookies, limit))

    def get_home_timeline(self, limit: int = 50) -> list[dict[str, Any]]:
        """Fetch the user's For You feed (algorithmic timeline). Returns the
        same shape as get_bookmarks, with engagement counts on each tweet."""
        cookies = _parse_netscape_cookies(self._cookies_path)
        return asyncio.run(self._fetch_home_timeline(cookies, limit))

    async def _fetch(self, cookies: dict[str, str], limit: int) -> list[dict[str, Any]]:
        import httpx
        from twikit.x_client_transaction import ClientTransaction
        from twikit.x_client_transaction.utils import handle_x_migration

        user_agent = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )

        async with httpx.AsyncClient(
            cookies={"ct0": cookies["ct0"], "auth_token": cookies["auth_token"]},
            headers={"User-Agent": user_agent},
            timeout=30,
            follow_redirects=True,
        ) as http:
            # Initialize the transaction-id generator. Twitter rotates the
            # ondemand.s JS bundle, so init() occasionally fails to find the
            # KEY_BYTE indices. Retry with backoff before giving up.
            tx = ClientTransaction()
            ct_headers = {
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "no-cache",
                "Referer": "https://x.com",
                "User-Agent": user_agent,
            }
            last_err: Exception | None = None
            for attempt in range(3):
                try:
                    await tx.init(http, ct_headers)
                    break
                except Exception as e:
                    last_err = e
                    if attempt < 2:
                        await asyncio.sleep(1 << attempt)
            else:
                raise RuntimeError(
                    "X anti-bot fingerprint failed after 3 attempts. "
                    "This is usually transient — try again in a minute. "
                    f"(last error: {last_err})"
                )

            tid = tx.generate_transaction_id(
                method="GET",
                path=urlparse(_BOOKMARKS_URL).path,
            )

            variables = json.dumps({
                "count": limit,
                "includePromotedContent": True,
            })
            features = json.dumps({
                "graphql_timeline_v2_bookmark_timeline": True,
                "creator_subscriptions_tweet_preview_api_enabled": True,
                "c9s_tweet_anatomy_moderator_badge_enabled": True,
                "tweetypie_unmention_optimization_enabled": True,
                "responsive_web_edit_tweet_api_enabled": True,
                "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
                "view_counts_everywhere_api_enabled": True,
                "longform_notetweets_consumption_enabled": True,
                "responsive_web_twitter_article_tweet_consumption_enabled": True,
                "tweet_awards_web_tipping_enabled": False,
                "longform_notetweets_rich_text_read_enabled": True,
                "longform_notetweets_inline_media_enabled": True,
                "rweb_video_timestamps_enabled": True,
                "responsive_web_graphql_exclude_directive_enabled": True,
                "verified_phone_label_enabled": False,
                "freedom_of_speech_not_reach_fetch_enabled": True,
                "standardized_nudges_misinfo": True,
                "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
                "responsive_web_media_download_video_enabled": False,
                "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
                "responsive_web_graphql_timeline_navigation_enabled": True,
                "responsive_web_enhance_cards_enabled": False,
            })
            headers = {
                "Authorization": f"Bearer {_BEARER}",
                "x-csrf-token": cookies["ct0"],
                "x-twitter-active-user": "yes",
                "x-twitter-auth-type": "OAuth2Session",
                "x-twitter-client-language": "en",
                "X-Client-Transaction-Id": tid,
                "Referer": "https://x.com/i/bookmarks",
                "Accept": "*/*",
            }

            resp = await http.get(
                _BOOKMARKS_URL,
                params={"variables": variables, "features": features},
                headers=headers,
            )
            resp.raise_for_status()
            return self._parse(resp.json())

    def _parse(self, data: dict) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        try:
            instructions = data["data"]["bookmark_timeline_v2"]["timeline"]["instructions"]
        except KeyError:
            return results
        return _parse_timeline_entries(_collect_entries(instructions))

    async def _fetch_home_timeline(self, cookies: dict[str, str], limit: int) -> list[dict[str, Any]]:
        """Fetch For You feed. Same auth dance as bookmarks but POST instead of GET."""
        import httpx

        user_agent = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        async with httpx.AsyncClient(
            cookies={"ct0": cookies["ct0"], "auth_token": cookies["auth_token"]},
            headers={"User-Agent": user_agent},
            timeout=30,
            follow_redirects=True,
        ) as http:
            tid = await _init_transaction_id(http, user_agent, _HOME_TIMELINE_URL, method="POST")
            body = {
                "variables": {
                    "count": limit,
                    "includePromotedContent": True,
                    "latestControlAvailable": True,
                    "requestContext": "launch",
                    "withCommunity": True,
                    "seenTweetIds": [],
                },
                "features": _GQL_FEATURES,
                "queryId": _HOME_TIMELINE_URL.rsplit("/", 2)[-2],
            }
            headers = {
                "Authorization": f"Bearer {_BEARER}",
                "x-csrf-token": cookies["ct0"],
                "x-twitter-active-user": "yes",
                "x-twitter-auth-type": "OAuth2Session",
                "x-twitter-client-language": "en",
                "X-Client-Transaction-Id": tid,
                "Referer": "https://x.com/home",
                "Accept": "*/*",
                "Content-Type": "application/json",
            }
            resp = await http.post(_HOME_TIMELINE_URL, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            try:
                instructions = data["data"]["home"]["home_timeline_urt"]["instructions"]
            except KeyError:
                return []
            return _parse_timeline_entries(_collect_entries(instructions))

    def get_user_tweets(self, screen_name: str, limit: int = 20) -> list[dict[str, Any]]:
        """Fetch recent tweets from a single user. Returns same shape as get_bookmarks,
        plus engagement counts (likes, retweets, views) on the source tweet."""
        cookies = _parse_netscape_cookies(self._cookies_path)
        return asyncio.run(_fetch_user_tweets(cookies, screen_name, limit))


async def _fetch_user_tweets(cookies: dict[str, str], screen_name: str, limit: int) -> list[dict[str, Any]]:
    """Use twikit's high-level Client for user-tweets (saves us reverse-engineering
    UserByScreenName + UserTweets GraphQL hashes). We patch the User class to
    tolerate X's schema drift (missing pinned_tweet_ids_str)."""
    import twikit
    from twikit.user import User

    # Idempotent monkey-patch: tolerate missing legacy fields X has stopped sending.
    if not getattr(User.__init__, "_orbit_patched", False):
        _orig_init = User.__init__

        def _patched_init(self, client, data):
            legacy = data.get("legacy", {}) or {}
            legacy.setdefault("pinned_tweet_ids_str", [])
            data["legacy"] = legacy
            return _orig_init(self, client, data)

        _patched_init._orbit_patched = True  # type: ignore[attr-defined]
        User.__init__ = _patched_init  # type: ignore[method-assign]

    c = twikit.Client("en-US")
    c.set_cookies(cookies)
    user = await c.get_user_by_screen_name(screen_name)
    raw = await c.get_user_tweets(user.id, "Tweets", count=limit)

    out: list[dict[str, Any]] = []
    for t in raw:
        text = (t.text or "").strip()
        text = re.sub(r"https://t\.co/\S+", "", text).strip()
        if not text:
            continue
        media_url, media_type = _extract_tweet_media(t)
        out.append({
            "text": text,
            "media_url": media_url,
            "media_type": media_type,
            "author": f"@{user.screen_name}",
            "url": f"https://x.com/{user.screen_name}/status/{t.id}",
            "tweet_id": t.id,
            "source_likes": int(getattr(t, "favorite_count", 0) or 0),
            "source_retweets": int(getattr(t, "retweet_count", 0) or 0),
            "source_views": int(getattr(t, "view_count", 0) or 0),
            "created_at": getattr(t, "created_at", None),
        })
    return out


def _extract_tweet_media(tweet) -> tuple[str | None, str | None]:
    """Pull media from a twikit Tweet object (which exposes .media as list of Media)."""
    media = getattr(tweet, "media", None) or []
    if not media:
        return None, None
    first = media[0]
    mtype = getattr(first, "type", None)
    if mtype in ("video", "animated_gif"):
        # twikit exposes streams via .streams on Media — pick highest bitrate mp4
        streams = getattr(first, "streams", None) or []
        mp4s = [s for s in streams if getattr(s, "content_type", "") == "video/mp4" and getattr(s, "url", None)]
        if mp4s:
            best = max(mp4s, key=lambda s: getattr(s, "bitrate", 0) or 0)
            return best.url, mtype
    if mtype == "photo":
        return getattr(first, "media_url", None) or getattr(first, "media_url_https", None), mtype
    return None, mtype
