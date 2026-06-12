"""Fetch + cache YouTube transcripts.

Transcripts don't change once published, so they're a perfect on-disk cache.
We store as plain text (joined snippets) — losing timestamps is fine for
draft generation.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

from youtube_transcript_api import YouTubeTranscriptApi


@dataclass
class Transcript:
    video_id: str
    text: str
    language: str
    snippet_count: int


class TranscriptUnavailable(RuntimeError):
    """No transcript could be fetched (disabled, region-locked, video private, etc.)."""


class YouTubeTranscriptClient:
    def __init__(self, cache_dir: Path | None = None, languages: tuple[str, ...] = ("en",)) -> None:
        self._cache_dir = cache_dir or Path.home() / ".orbit" / "transcripts"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._languages = languages
        self._api = YouTubeTranscriptApi()

    def fetch(self, video_id: str, force: bool = False) -> Transcript:
        """Return the transcript for a video, hitting cache when possible."""
        cached = self._read_cache(video_id)
        if cached and not force:
            return cached
        try:
            ft = self._api.fetch(video_id, languages=list(self._languages))
        except Exception as e:
            # youtube-transcript-api raises a zoo of specific exceptions
            # (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable, etc.).
            # We normalize to one TranscriptUnavailable so callers handle it once.
            raise TranscriptUnavailable(f"Could not fetch transcript for {video_id}: {e}") from e

        text = " ".join(s.text for s in ft.snippets).strip()
        transcript = Transcript(
            video_id=video_id,
            text=text,
            language=ft.language,
            snippet_count=len(ft.snippets),
        )
        self._write_cache(transcript)
        return transcript

    def _cache_path(self, video_id: str) -> Path:
        return self._cache_dir / f"{video_id}.txt"

    def _read_cache(self, video_id: str) -> Transcript | None:
        path = self._cache_path(video_id)
        if not path.exists():
            return None
        lines = path.read_text(encoding="utf-8").splitlines()
        # First two lines are metadata: language, snippet_count
        if len(lines) < 3 or not lines[0].startswith("# language:"):
            # Old or malformed cache — ignore
            return None
        language = lines[0].split(":", 1)[1].strip()
        snippet_count = int(lines[1].split(":", 1)[1].strip())
        text = "\n".join(lines[2:])
        return Transcript(
            video_id=video_id,
            text=text,
            language=language,
            snippet_count=snippet_count,
        )

    def _write_cache(self, t: Transcript) -> None:
        header = f"# language: {t.language}\n# snippet_count: {t.snippet_count}\n"
        self._cache_path(t.video_id).write_text(header + t.text, encoding="utf-8")
