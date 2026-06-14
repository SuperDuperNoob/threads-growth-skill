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

    def get_metrics(
        self, post_urns: list[str], *, enrich_social: bool = True
    ) -> dict[str, dict[str, Any]]:
        # Uses the personal shareStatistics endpoint (q=shares) which works for
        # urn:li:person: authors. The organizationalEntityShareStatistics endpoint
        # requires org admin scope and returns empty for personal accounts.
        #
        # shareStatistics returns impressions + clicks reliably, but likeCount /
        # commentCount come back 0 for personal authors — those live on the
        # socialActions endpoint. When `enrich_social` is set we backfill them
        # per-URN (see `_fetch_social_counts`); it degrades gracefully to the
        # shareStatistics zeros if the token lacks r_member_social scope.
        urns_param = ",".join(post_urns)
        resp = self._http.get(
            f"{BASE_URL}/shareStatistics",
            params={
                "q": "shares",
                "shares": f"List({urns_param})",
            },
        )
        resp.raise_for_status()
        result: dict[str, dict[str, Any]] = {}
        for el in resp.json().get("elements", []):
            urn = el.get("share", "")
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

        if enrich_social:
            self.enrich_social_counts(result, post_urns)

        return result

    def enrich_social_counts(
        self, metrics_map: dict[str, dict[str, Any]], urns: list[str]
    ) -> None:
        """Backfill likes/comments on `metrics_map` in-place for the given URNs.

        One socialActions call per URN (no batch endpoint exists). Callers limit
        `urns` to the posts worth the quota — see _sync_linkedin's recent-50 cap.
        Never lowers an existing value: a failed/under-scoped read returns 0 and
        is ignored, so we keep whatever shareStatistics already provided.
        """
        for urn in urns:
            social = self._fetch_social_counts(urn)
            if social is None:
                continue
            row = metrics_map.setdefault(urn, {
                "views": 0, "likes": 0, "comments": 0,
                "shares": 0, "clicks": 0, "reposts": 0, "saves": 0,
            })
            likes, comments = social
            if likes > row.get("likes", 0):
                row["likes"] = likes
            if comments > row.get("comments", 0):
                row["comments"] = comments

    def _fetch_social_counts(self, urn: str) -> tuple[int, int] | None:
        """Return (likes, comments) for a single share/ugcPost URN.

        Hits /v2/socialActions/{urn}. Returns None on any failure (missing
        r_member_social scope → 403, deleted post → 404, network error) so the
        caller falls back to shareStatistics values instead of breaking sync.
        """
        import urllib.parse
        encoded = urllib.parse.quote(urn, safe="")
        try:
            resp = self._http.get(f"{BASE_URL}/socialActions/{encoded}")
            if resp.status_code != 200:
                return None
            data = resp.json()
            likes = data.get("likesSummary", {}).get("totalLikes", 0)
            comments = data.get("commentsSummary", {}).get(
                "aggregatedTotalComments", 0
            )
            return int(likes), int(comments)
        except Exception:
            return None
