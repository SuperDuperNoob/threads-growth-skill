from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
import httpx

BASE_URL = "https://api.linkedin.com/v2"


class LinkedInClient:
    def __init__(self, access_token: str | None) -> None:
        if not access_token:
            raise ValueError("LinkedIn access_token is required")
        self._http = httpx.Client(
            headers={
                "Authorization": f"Bearer {access_token}",
                "LinkedIn-Version": "202401",
            },
            timeout=30,
        )

    def get_posts(self, author_urn: str, count: int = 50) -> list[dict[str, Any]]:
        resp = self._http.get(
            f"{BASE_URL}/ugcPosts",
            params={"q": "authors", "authors": f"List({author_urn})", "count": count},
        )
        resp.raise_for_status()
        posts = []
        for el in resp.json().get("elements", []):
            content = (
                el.get("specificContent", {})
                .get("com.linkedin.ugc.ShareContent", {})
                .get("shareCommentary", {})
                .get("text", "")
            )
            created_ms = el.get("created", {}).get("time", 0)
            created_at = datetime.fromtimestamp(
                created_ms / 1000, tz=timezone.utc
            ).isoformat()
            posts.append({
                "external_id": el["id"],
                "platform": "linkedin",
                "content": content,
                "published_at": created_at,
            })
        return posts

    def get_metrics(self, post_urns: list[str]) -> dict[str, dict[str, Any]]:
        urns_param = ",".join(post_urns)
        resp = self._http.get(
            f"{BASE_URL}/organizationalEntityShareStatistics",
            params={
                "q": "organizationalEntity",
                "shares": f"List({urns_param})",
            },
        )
        resp.raise_for_status()
        result: dict[str, dict[str, Any]] = {}
        for el in resp.json().get("elements", []):
            urn = el.get("share") or el.get("organizationalEntity", "")
            stats = el.get("totalShareStatistics", {})
            result[urn] = {
                "views": stats.get("impressionCount", 0),
                "likes": stats.get("likeCount", 0),
                "comments": stats.get("commentCount", 0),
                "shares": stats.get("shareCount", 0),
                "clicks": stats.get("clickCount", 0),
                "reposts": 0,
                "saves": 0,
            }
        return result
