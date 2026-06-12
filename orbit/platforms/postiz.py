"""Thin wrapper around the Postiz CLI.

Orbit shells out to `postiz` rather than reimplementing the API — Postiz already
handles auth, retries, and 28+ platform-specific quirks. We only need to
construct the right argv and parse the response.
"""
from __future__ import annotations
import json
import shutil
import subprocess
from typing import Any


class PostizUnavailable(RuntimeError):
    """Raised when the postiz CLI isn't installed or isn't authenticated."""


def ensure_available() -> None:
    """Verify postiz is installed and authenticated. Raises PostizUnavailable otherwise."""
    if shutil.which("postiz") is None:
        raise PostizUnavailable(
            "Postiz CLI not found. Install with: npm install -g postiz, "
            "then authenticate with: postiz auth:login"
        )
    try:
        result = subprocess.run(
            ["postiz", "auth:status"],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        raise PostizUnavailable(f"Postiz CLI failed: {e}") from e
    if result.returncode != 0 or "Authentication method" not in result.stdout:
        raise PostizUnavailable(
            "Postiz not authenticated. Run: postiz auth:login"
        )


def integrations() -> list[dict[str, Any]]:
    """List the user's connected Postiz integrations."""
    result = subprocess.run(
        ["postiz", "integrations:list"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"postiz integrations:list failed: {result.stderr or result.stdout}")
    # CLI prints a banner line before the JSON array — find the array start.
    out = result.stdout
    start = out.find("[")
    if start < 0:
        raise RuntimeError(f"Unexpected postiz output: {out[:200]}")
    return json.loads(out[start:])


def integration_id_for(identifier: str) -> str | None:
    """Find an integration ID by identifier ('threads', 'facebook', etc.). None if missing."""
    for it in integrations():
        if it.get("identifier") == identifier and not it.get("disabled"):
            return it.get("id")
    return None


def schedule_post(
    content: str,
    when_iso: str,
    integration_ids: list[str],
    media_url: str | None = None,
    as_draft: bool = False,
    comment: str | None = None,
    settings: dict | None = None,
) -> str:
    """Schedule a post on the given Postiz integrations. Returns the Postiz post id(s).

    If `comment` is set, schedules main post + a threaded reply.
    If `settings` is set, passes --settings to provide platform-specific config
    (e.g. {"post_type": "post"} for Facebook to skip the UI prompt).
    """
    if not integration_ids:
        raise ValueError("schedule_post requires at least one integration_id")
    cmd = [
        "postiz", "posts:create",
        "-c", content,
    ]
    if media_url:
        cmd += ["-m", media_url]
    if comment:
        cmd += ["-c", comment]
    cmd += [
        "-s", when_iso,
        "-t", "draft" if as_draft else "schedule",
        "-i", ",".join(integration_ids),
    ]
    if settings:
        cmd += ["--settings", json.dumps(settings)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"postiz posts:create failed: {result.stderr or result.stdout}")
    # Postiz prints "✅ Post created successfully!" then a JSON array (one entry
    # per integration). Find the first { or [ and parse from there.
    out = result.stdout
    json_start = min(
        (i for i in (out.find("{"), out.find("[")) if i >= 0),
        default=-1,
    )
    if json_start < 0:
        # Fall back to grabbing the last non-empty line as the id
        return out.strip().splitlines()[-1].strip()
    try:
        data = json.loads(out[json_start:])
    except json.JSONDecodeError:
        return out[json_start:].strip()
    # Multi-integration: list of {postId, integration} dicts
    if isinstance(data, list):
        return ",".join(item.get("postId", "") for item in data if item.get("postId"))
    if isinstance(data, dict):
        return data.get("id") or data.get("postId") or json.dumps(data)
    return str(data)
