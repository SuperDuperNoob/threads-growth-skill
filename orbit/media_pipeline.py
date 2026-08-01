"""Download X media + upload to Postiz so external URLs become Postiz-hosted URLs.

Postiz hard-rejects external media URLs (must live on uploads.postiz.com). This
module does the two-step dance:
  1. curl the external URL to ~/.orbit/media/<key>.<ext>
  2. postiz upload that file
  3. return the uploads.postiz.com URL

Downloads are cached on disk by `key` (e.g. the draft id) so re-handoff doesn't
re-fetch. A small JSON index also caches the uploads.postiz.com URL per draft
so re-uploads are skipped too.
"""
from __future__ import annotations
import json
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import httpx


_MEDIA_DIR = Path.home() / ".orbit" / "media"
_INDEX_PATH = _MEDIA_DIR / "uploads_index.json"

# Postiz media upload can be slow for videos (Twitter amplify clips are tens of
# MB). 120s was too tight — it timed out mid-upload on real Seedance/motion
# videos, leaving drafts stuck at `scheduled`. 300s covers large videos while
# still bounding a genuinely wedged upload (important for headless Hermes runs).
_UPLOAD_TIMEOUT_SECONDS = 300


class MediaPipelineError(RuntimeError):
    """Raised when download or upload fails — caller decides if it's fatal."""


def attach_media(draft_id: int, source_url: str, *, force: bool = False) -> str:
    """Download source_url, upload to Postiz, return the uploads.postiz.com URL.

    Caches both the download (file on disk) and the uploaded URL (in JSON index)
    so re-handoffs of the same draft are free.
    """
    _MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    # Cache hit?
    index = _load_index()
    cached = index.get(str(draft_id))
    if cached and not force:
        return cached

    local_path = _download(draft_id, source_url, force=force)
    postiz_url = _postiz_upload(local_path)
    index[str(draft_id)] = postiz_url
    _save_index(index)
    return postiz_url


def _download(draft_id: int, source_url: str, *, force: bool) -> Path:
    """Fetch source_url to ~/.orbit/media/<draft_id>.<ext>. Returns the path."""
    ext = _guess_ext(source_url)
    path = _MEDIA_DIR / f"{draft_id}{ext}"
    if path.exists() and not force:
        return path
    try:
        with httpx.stream("GET", source_url, follow_redirects=True, timeout=60) as r:
            r.raise_for_status()
            with path.open("wb") as f:
                for chunk in r.iter_bytes(chunk_size=64 * 1024):
                    f.write(chunk)
    except httpx.HTTPError as e:
        raise MediaPipelineError(f"download failed for {source_url}: {e}") from e
    if path.stat().st_size == 0:
        path.unlink(missing_ok=True)
        raise MediaPipelineError(f"download produced empty file: {source_url}")
    return path


def _postiz_upload(path: Path) -> str:
    """Run `postiz upload <path>`, parse the JSON response, return the URL."""
    result = subprocess.run(
        ["postiz", "upload", str(path)],
        capture_output=True, text=True, timeout=_UPLOAD_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise MediaPipelineError(
            f"postiz upload failed: {result.stderr or result.stdout}"
        )
    out = result.stdout
    brace = out.find("{")
    if brace < 0:
        raise MediaPipelineError(f"unexpected postiz upload output: {out[:200]}")
    try:
        data = json.loads(out[brace:])
    except json.JSONDecodeError as e:
        raise MediaPipelineError(f"could not parse postiz upload JSON: {e}") from e
    url = data.get("path")
    if not url:
        raise MediaPipelineError(f"postiz upload returned no path: {data}")
    return url


def _guess_ext(url: str) -> str:
    """Pull the file extension off the URL path, default .bin if unknown."""
    path = urlparse(url).path
    if "." in path:
        ext = "." + path.rsplit(".", 1)[-1].lower()
        # Strip query-string garbage like '.mp4?tag=14'
        ext = ext.split("?")[0]
        if 2 <= len(ext) <= 6 and all(c.isalnum() or c == "." for c in ext):
            return ext
    return ".bin"


def _load_index() -> dict[str, str]:
    if not _INDEX_PATH.exists():
        return {}
    try:
        return json.loads(_INDEX_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def _save_index(index: dict[str, str]) -> None:
    _MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    _INDEX_PATH.write_text(json.dumps(index, indent=2))
