from __future__ import annotations
from typing import Any
import httpx

BASE_URL = "https://www.googleapis.com/youtube/v3"


class YouTubeClient:
    def __init__(self, api_key: str | None, channel_id: str) -> None:
        if not api_key:
            raise ValueError("YouTube api_key is required")
        self._key = api_key
        self.channel_id = channel_id
        self._http = httpx.Client(timeout=30)

    def get_videos(self, max_results: int = 50) -> list[dict[str, Any]]:
        search_resp = self._http.get(
            f"{BASE_URL}/search",
            params={
                "key": self._key,
                "channelId": self.channel_id,
                "part": "id",
                "order": "date",
                "maxResults": max_results,
                "type": "video",
            },
        )
        search_resp.raise_for_status()
        video_ids = [
            item["id"]["videoId"]
            for item in search_resp.json().get("items", [])
        ]
        if not video_ids:
            return []

        details_resp = self._http.get(
            f"{BASE_URL}/videos",
            params={
                "key": self._key,
                "id": ",".join(video_ids),
                "part": "snippet,statistics",
            },
        )
        details_resp.raise_for_status()

        videos = []
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
