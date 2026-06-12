from __future__ import annotations
from typing import Any
import httpx

BASE_URL = "https://graph.threads.net/v1.0"


class ThreadsClient:
    def __init__(self, access_token: str | None, user_id: str | None) -> None:
        if not access_token:
            raise ValueError("Threads access_token is required")
        if not user_id:
            raise ValueError("Threads user_id is required")
        self._token = access_token
        self._user_id = user_id
        self._http = httpx.Client(timeout=30)

    def _params(self, extra: dict | None = None) -> dict:
        p = {"access_token": self._token}
        if extra:
            p.update(extra)
        return p

    def get_posts(self, limit: int = 50) -> list[dict[str, Any]]:
        resp = self._http.get(
            f"{BASE_URL}/{self._user_id}/threads",
            params=self._params({
                "fields": "id,text,timestamp,media_type",
                "limit": limit,
            }),
        )
        resp.raise_for_status()
        posts = []
        for el in resp.json().get("data", []):
            posts.append({
                "external_id": el["id"],
                "platform": "threads",
                "content": el.get("text", ""),
                "published_at": el.get("timestamp", ""),
            })
        return posts

    def create_post(self, text: str) -> str:
        """Publish a text-only Thread. Returns the published thread id.

        Two-step Threads Graph API: create a media container, then publish it.
        Docs: https://developers.facebook.com/docs/threads/posts
        """
        create = self._http.post(
            f"{BASE_URL}/{self._user_id}/threads",
            params=self._params({"media_type": "TEXT", "text": text}),
        )
        create.raise_for_status()
        creation_id = create.json().get("id")
        if not creation_id:
            raise RuntimeError(f"Threads create returned no id: {create.text}")

        publish = self._http.post(
            f"{BASE_URL}/{self._user_id}/threads_publish",
            params=self._params({"creation_id": creation_id}),
        )
        publish.raise_for_status()
        thread_id = publish.json().get("id")
        if not thread_id:
            raise RuntimeError(f"Threads publish returned no id: {publish.text}")
        return thread_id

    def get_metrics(self, post_id: str) -> dict[str, Any]:
        resp = self._http.get(
            f"{BASE_URL}/{post_id}/insights",
            params=self._params({
                "metric": "views,likes,replies,reposts,quotes",
            }),
        )
        resp.raise_for_status()
        result: dict[str, Any] = {
            "views": 0, "likes": 0, "comments": 0,
            "shares": 0, "reposts": 0, "clicks": 0, "saves": 0,
        }
        for item in resp.json().get("data", []):
            name = item.get("name")
            value = item.get("values", [{}])[0].get("value", 0) if item.get("values") else item.get("total_value", {}).get("value", 0)
            if name == "views":
                result["views"] = value
            elif name == "likes":
                result["likes"] = value
            elif name == "replies":
                result["comments"] = value
            elif name in ("reposts", "quotes"):
                result["reposts"] += value
        return result
