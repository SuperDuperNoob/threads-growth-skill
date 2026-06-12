"""LinkedIn Community Management API client.

Requires a dedicated LinkedIn dev app with Community Management API approved
(separate from the existing Share-on-LinkedIn app). Uses the modern versioned
/rest endpoints, NOT the legacy /v2/ugcPosts which returns 403 for personal apps.

Credentials live under `linkedin_analytics.*` in config — distinct namespace
from the existing `linkedin.*` so the Postiz-integrated app isn't disturbed.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
import urllib.parse

import httpx


# LinkedIn's versioned API requires a date-stamped Version header. Bump quarterly
# as LinkedIn deprecates older versions; current stable as of mid-2026 is 202507.
DEFAULT_VERSION = "202507"


class LinkedInCMClient:
    def __init__(
        self,
        access_token: str,
        person_urn: str,
        version: str = DEFAULT_VERSION,
    ) -> None:
        if not access_token:
            raise ValueError("access_token required")
        if not person_urn:
            raise ValueError("person_urn required (urn:li:person:<id>)")
        self._urn = person_urn
        self._http = httpx.Client(
            base_url="https://api.linkedin.com",
            headers={
                "Authorization": f"Bearer {access_token}",
                "LinkedIn-Version": version,
                "X-Restli-Protocol-Version": "2.0.0",
            },
            timeout=30,
        )

    def get_posts(self, count: int = 20) -> list[dict[str, Any]]:
        """List your own recent posts via /rest/posts?q=author&author=<urn>."""
        encoded_urn = urllib.parse.quote(self._urn, safe="")
        r = self._http.get(
            "/rest/posts",
            params={"q": "author", "author": encoded_urn, "count": count},
        )
        r.raise_for_status()
        elements = (r.json() or {}).get("elements") or []
        out = []
        for el in elements:
            commentary = el.get("commentary") or ""
            created_ms = el.get("createdAt") or el.get("publishedAt") or 0
            created_iso = (
                datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc).isoformat()
                if created_ms else ""
            )
            out.append({
                "external_id": el.get("id"),  # urn:li:share:... or urn:li:ugcPost:...
                "platform": "linkedin",
                "content": commentary,
                "published_at": created_iso,
            })
        return out

    def get_engagement(self, post_urn: str) -> dict[str, int]:
        """Pull likes + comments + reshares for a single post URN via
        /rest/socialActions/{urn}. Returns 0s if the endpoint is silent."""
        encoded = urllib.parse.quote(post_urn, safe="")
        r = self._http.get(f"/rest/socialActions/{encoded}")
        r.raise_for_status()
        data = r.json() or {}
        return {
            "views": 0,  # /rest/socialActions doesn't expose views — see note below
            "likes": int((data.get("likesSummary") or {}).get("totalLikes") or 0),
            "comments": int((data.get("commentsSummary") or {}).get("totalFirstLevelComments") or 0),
            "reposts": int((data.get("sharesSummary") or {}).get("totalShares") or 0),
            "shares": 0,
            "clicks": 0,
            "saves": 0,
        }

    def get_impressions(self, post_urns: list[str]) -> dict[str, int]:
        """Pull impression counts via /rest/organizationalEntityShareStatistics
        (works for member URNs too with the right scope). Returns {urn: impressions}.
        Empty map if the endpoint denies access."""
        if not post_urns:
            return {}
        # Member-level analytics use memberShareStatistics under CM API.
        # Best-effort: if the endpoint isn't accessible to this token's scope,
        # callers fall back to engagement-only metrics.
        try:
            urns_param = ",".join(urllib.parse.quote(u, safe="") for u in post_urns)
            r = self._http.get(
                "/rest/memberShareStatistics",
                params={"q": "shares", "shares": f"List({urns_param})"},
            )
            r.raise_for_status()
        except httpx.HTTPError:
            return {}
        out: dict[str, int] = {}
        for el in (r.json() or {}).get("elements") or []:
            urn = el.get("share") or el.get("ugcPost")
            stats = el.get("totalShareStatistics") or {}
            out[urn] = int(stats.get("impressionCount") or 0)
        return out
