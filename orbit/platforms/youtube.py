from __future__ import annotations
from typing import Any, Callable
import httpx

BASE_URL = "https://www.googleapis.com/youtube/v3"
ANALYTICS_URL = "https://youtubeanalytics.googleapis.com/v2"
_TOKEN_URL = "https://oauth2.googleapis.com/token"


class YouTubeClient:
    def __init__(
        self,
        access_token: str | None,
        channel_id: str,
        client_id: str | None = None,
        client_secret: str | None = None,
        refresh_token: str | None = None,
        on_token_refresh: Callable[[str], None] | None = None,
    ) -> None:
        """on_token_refresh: called with the fresh access_token whenever auto-refresh
        succeeds, so the caller can persist it to config. Without this, a refreshed
        token survives only the current process — next run reuses the dead token."""
        if not access_token:
            raise ValueError("YouTube access_token is required")
        if not channel_id:
            raise ValueError("YouTube channel_id is required")
        self.channel_id = channel_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._on_token_refresh = on_token_refresh
        self._http = httpx.Client(
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30,
        )

    def _refresh_access_token(self) -> bool:
        if not (self._client_id and self._client_secret and self._refresh_token):
            return False
        try:
            resp = httpx.post(
                _TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                timeout=15,
            )
            resp.raise_for_status()
            new_token = resp.json().get("access_token")
            if new_token:
                self._http.headers["Authorization"] = f"Bearer {new_token}"
                if self._on_token_refresh:
                    try:
                        self._on_token_refresh(new_token)
                    except Exception:
                        # Persistence failure shouldn't break the in-memory refresh.
                        pass
                return True
        except Exception:
            pass
        return False

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        resp = self._http.request(method, url, **kwargs)
        if resp.status_code == 401 and self._refresh_access_token():
            resp = self._http.request(method, url, **kwargs)
        return resp

    def _get(self, path: str, params: dict) -> httpx.Response:
        return self._request("GET", f"{BASE_URL}/{path}", params=params)

    def _analytics_get(self, path: str, params: dict) -> httpx.Response:
        """GET against the YouTube Analytics API (separate host from Data API)."""
        return self._request("GET", f"{ANALYTICS_URL}/{path}", params=params)

    # YouTube Data API caps both `search.maxResults` and the `videos` id-batch at 50.
    _PAGE_SIZE = 50

    def get_videos(self, max_videos: int = 500) -> list[dict[str, Any]]:
        """Fetch up to `max_videos` of the channel's videos, newest first.

        Paginates the `search` endpoint via nextPageToken to collect IDs, then
        hydrates them in `videos` batches of 50. Without pagination this capped
        silently at the most recent 50 — older posts never received metric updates.

        `max_videos` is a quota guard: `search` costs 100 units/page, so a huge
        channel could otherwise blow the daily 10k-unit quota in one sync.
        """
        video_ids = self._list_video_ids(max_videos)
        if not video_ids:
            return []

        videos: list[dict[str, Any]] = []
        for start in range(0, len(video_ids), self._PAGE_SIZE):
            batch = video_ids[start : start + self._PAGE_SIZE]
            details_resp = self._get(
                "videos",
                {"id": ",".join(batch), "part": "snippet,statistics"},
            )
            details_resp.raise_for_status()
            for item in details_resp.json().get("items", []):
                stats = item.get("statistics", {})
                videos.append({
                    "external_id": item["id"],
                    "platform": "youtube",
                    "content": item["snippet"]["title"],
                    "published_at": item["snippet"]["publishedAt"],
                    "views": int(stats.get("viewCount", 0)),
                    "likes": int(stats.get("likeCount", 0)),
                    "comments": int(stats.get("commentCount", 0)),
                    "shares": 0,
                    "reposts": 0,
                    "clicks": 0,
                    "saves": 0,
                })
        return videos

    def _list_video_ids(self, max_videos: int) -> list[str]:
        """Page through `search` collecting video IDs until exhausted or capped."""
        ids: list[str] = []
        page_token: str | None = None
        while len(ids) < max_videos:
            params: dict[str, Any] = {
                "channelId": self.channel_id,
                "part": "id",
                "order": "date",
                "maxResults": min(self._PAGE_SIZE, max_videos - len(ids)),
                "type": "video",
            }
            if page_token:
                params["pageToken"] = page_token
            resp = self._get("search", params)
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("items", []):
                vid = item.get("id", {}).get("videoId")
                if vid:
                    ids.append(vid)
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return ids

    def get_external_traffic_sources(
        self,
        start_date: str,
        end_date: str,
        video_id: str | None = None,
        max_results: int = 25,
    ) -> list[dict[str, Any]]:
        """Pull external referrer breakdown (reddit.com, twitter.com, etc.) from
        the YouTube Analytics API.

        Args:
          start_date / end_date: 'YYYY-MM-DD'
          video_id: if set, scope to one video; otherwise channel-wide
          max_results: top N referrers by views (default 25)

        Returns: [{'referrer': 'reddit.com', 'views': 142, 'minutes_watched': 530}, ...]
        Returns empty list if the token lacks yt-analytics.readonly scope (403)
        or if there's no external traffic in the window.
        """
        params: dict[str, Any] = {
            "ids": f"channel=={self.channel_id}",
            "startDate": start_date,
            "endDate": end_date,
            "metrics": "views,estimatedMinutesWatched",
            "dimensions": "insightTrafficSourceDetail",
            "filters": "insightTrafficSourceType==EXT_URL",
            "sort": "-views",
            "maxResults": max_results,
        }
        if video_id:
            # YouTube Analytics filters are semicolon-joined
            params["filters"] = f"insightTrafficSourceType==EXT_URL;video=={video_id}"
        resp = self._analytics_get("reports", params)
        if resp.status_code == 403:
            return []  # Scope missing — caller can detect via empty + log
        resp.raise_for_status()
        data = resp.json()
        rows = data.get("rows", []) or []
        # rows are [referrer_string, views, minutes_watched]
        return [
            {
                "referrer": r[0],
                "views": int(r[1] or 0),
                "minutes_watched": int(r[2] or 0),
            }
            for r in rows
        ]

    def extract_metrics(self, videos: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {
            v["external_id"]: {
                "views": v.get("views", 0),
                "likes": v.get("likes", 0),
                "comments": v.get("comments", 0),
                "shares": v.get("shares", 0),
                "reposts": v.get("reposts", 0),
                "clicks": v.get("clicks", 0),
                "saves": v.get("saves", 0),
            }
            for v in videos
        }
