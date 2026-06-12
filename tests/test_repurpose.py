"""Tests for orbit.commands.repurpose pure helpers + transcript cache."""
from pathlib import Path

from orbit.commands.repurpose import _parse_moments, _parse_picks
from orbit.platforms.youtube_transcript import Transcript, YouTubeTranscriptClient


# --- _parse_moments ---

def test_parse_moments_three_sections():
    text = "[1] First moment text.\n\n[2] Second moment.\n\n[3] Third moment."
    out = _parse_moments(text)
    assert len(out) == 3
    assert "First moment" in out[0]
    assert "Second moment" in out[1]


def test_parse_moments_handles_preamble():
    """Preamble before [1] should be ignored. (Trailing text after the last block
    may bleed in — that's an LLM-prompt issue, mitigated by asking Claude not to
    add closing remarks. Human review catches edge cases.)"""
    text = "Here are the moments:\n\n[1] First.\n[2] Second."
    out = _parse_moments(text)
    assert len(out) == 2
    assert "Here are the moments" not in out[0]


def test_parse_moments_empty():
    assert _parse_moments("no numbered sections here") == []


def test_parse_moments_skips_empty_sections():
    text = "[1] Real moment.\n[2]\n[3] Another real one."
    out = _parse_moments(text)
    assert len(out) == 2


# --- _parse_picks ---

def test_parse_picks_single():
    assert _parse_picks("1", 3) == [0]


def test_parse_picks_comma():
    assert _parse_picks("1,3", 3) == [0, 2]


def test_parse_picks_drops_out_of_range():
    assert _parse_picks("1,5", 3) == [0]


def test_parse_picks_empty():
    assert _parse_picks("", 3) == []


def test_parse_picks_dedupes():
    assert _parse_picks("1,1,2", 3) == [0, 1]


# --- transcript cache ---

def test_transcript_cache_roundtrip(tmp_path: Path):
    client = YouTubeTranscriptClient(cache_dir=tmp_path)
    # Manually write a cache entry; _write_cache is private but we exercise via fetch fallback.
    fake = Transcript(
        video_id="abc123",
        text="hello world\nthis is a transcript",
        language="English (auto-generated)",
        snippet_count=42,
    )
    client._write_cache(fake)

    # Round-trip through _read_cache
    got = client._read_cache("abc123")
    assert got is not None
    assert got.video_id == "abc123"
    assert got.text == "hello world\nthis is a transcript"
    assert got.language == "English (auto-generated)"
    assert got.snippet_count == 42


def test_transcript_cache_missing_returns_none(tmp_path: Path):
    client = YouTubeTranscriptClient(cache_dir=tmp_path)
    assert client._read_cache("nonexistent") is None


def test_transcript_cache_malformed_returns_none(tmp_path: Path):
    """If the cache file exists but doesn't have our header, we shouldn't crash."""
    (tmp_path / "bad.txt").write_text("just some text with no header")
    client = YouTubeTranscriptClient(cache_dir=tmp_path)
    assert client._read_cache("bad") is None
