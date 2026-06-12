"""Find the GitHub repo for an open-source project mentioned in a draft.

Two strategies, fastest first:
1. Regex: explicit github.com/<org>/<repo> URL in the draft text.
2. Claude: identify the project name, propose a repo, we HEAD-check it.

Returns the canonical URL (`https://github.com/<org>/<repo>`) or None.
Results are cached to ~/.orbit/github_links.json so repeat lookups are free.
"""
from __future__ import annotations
import json
import re
from pathlib import Path

import httpx

_CACHE_PATH = Path.home() / ".orbit" / "github_links.json"
_REPO_RE = re.compile(r"https?://github\.com/([\w.-]+)/([\w.-]+)", re.IGNORECASE)


def find_github_repo(draft_text: str, ai=None) -> str | None:
    """Find the GitHub URL for the OSS project this draft is about. None if no match.

    `ai` is an optional anthropic.Anthropic client. If provided, we'll ask Claude
    when the regex finds nothing. Without it, regex-only.
    """
    if not draft_text:
        return None

    # Strategy 1: explicit github.com URL in the text
    m = _REPO_RE.search(draft_text)
    if m:
        org, repo = m.group(1), m.group(2).rstrip(".,;:")
        url = f"https://github.com/{org}/{repo}"
        return _verify_or_none(url)

    # Strategy 2: ask Claude to identify the project
    if ai is None:
        return None

    cached = _cache_lookup(draft_text)
    if cached is not None:
        # Empty-string sentinel means "Claude already said no project" — don't re-ask
        return cached or None

    repo = _ask_claude_for_repo(ai, draft_text)
    verified = _verify_or_none(repo) if repo else None
    # Cache the verified URL (or empty string to remember "no" answers)
    _cache_store(draft_text, verified or "")
    return verified


def _ask_claude_for_repo(ai, draft_text: str) -> str | None:
    prompt = f"""This is a social media post about an open-source project. If you're confident which OSS project it's about, reply with ONLY the GitHub URL in the form https://github.com/<org>/<repo>. If you're not sure, or it's not about a specific OSS project, reply with the single word: NONE.

Post:
\"\"\"
{draft_text}
\"\"\"

Reply (URL or NONE):"""
    msg = ai.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=80,
        messages=[{"role": "user", "content": prompt}],
    )
    reply = msg.content[0].text.strip()
    if reply.upper().startswith("NONE"):
        return None
    m = _REPO_RE.search(reply)
    if not m:
        return None
    return f"https://github.com/{m.group(1)}/{m.group(2).rstrip('.,;:')}"


def _verify_or_none(url: str | None) -> str | None:
    """HEAD-check the URL. Returns it if 200/301, else None.
    Cheap protection against Claude hallucinating a plausible but nonexistent repo."""
    if not url:
        return None
    try:
        r = httpx.head(url, follow_redirects=True, timeout=8)
        if r.status_code < 400:
            return url
    except httpx.HTTPError:
        pass
    return None


def _cache_lookup(draft_text: str) -> str | None:
    """Cache key: first 200 chars of draft text (drafts are short and unique enough)."""
    if not _CACHE_PATH.exists():
        return None
    try:
        cache = json.loads(_CACHE_PATH.read_text())
    except json.JSONDecodeError:
        return None
    return cache.get(_cache_key(draft_text))


def _cache_store(draft_text: str, value: str) -> None:
    cache: dict[str, str] = {}
    if _CACHE_PATH.exists():
        try:
            cache = json.loads(_CACHE_PATH.read_text())
        except json.JSONDecodeError:
            pass
    cache[_cache_key(draft_text)] = value
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2))


def _cache_key(draft_text: str) -> str:
    return draft_text.strip()[:200]
