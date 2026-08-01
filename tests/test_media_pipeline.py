"""Tests for the X-to-Postiz media download + upload pipeline.

We don't hit the network or shell out to `postiz` in tests — those calls are
mocked. The pure-logic helpers (extension parsing, cache lookup) get direct tests.
"""
import json
from pathlib import Path

import pytest

from orbit import media_pipeline


# ---- _guess_ext ----


def test_guess_ext_strips_query_string():
    """X video URLs end with '.mp4?tag=14' — the extension must drop the query."""
    assert media_pipeline._guess_ext(
        "https://video.twimg.com/amplify_video/X/vid/Y.mp4?tag=14"
    ) == ".mp4"


def test_guess_ext_photo():
    assert media_pipeline._guess_ext("https://pbs.twimg.com/media/abc.jpg") == ".jpg"
    assert media_pipeline._guess_ext("https://pbs.twimg.com/media/abc.png") == ".png"


def test_guess_ext_unknown_falls_back():
    """No extension and no recognizable format → .bin so we don't crash."""
    assert media_pipeline._guess_ext("https://example.com/file") == ".bin"


def test_guess_ext_caps_length():
    """Pathological '.this_is_not_an_extension' shouldn't be used as the file ext."""
    # The guard is 2 <= len(ext) <= 6; long bogus strings fall back to .bin.
    assert media_pipeline._guess_ext("https://x.com/.thisIsNotAnExtension") == ".bin"


# ---- cache index ----


def test_index_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(media_pipeline, "_MEDIA_DIR", tmp_path)
    monkeypatch.setattr(media_pipeline, "_INDEX_PATH", tmp_path / "idx.json")

    assert media_pipeline._load_index() == {}
    media_pipeline._save_index({"42": "https://uploads.postiz.com/abc.jpg"})
    assert media_pipeline._load_index() == {"42": "https://uploads.postiz.com/abc.jpg"}


def test_index_handles_malformed_file(tmp_path, monkeypatch):
    """A corrupted index file shouldn't crash the next handoff — return empty."""
    monkeypatch.setattr(media_pipeline, "_MEDIA_DIR", tmp_path)
    monkeypatch.setattr(media_pipeline, "_INDEX_PATH", tmp_path / "idx.json")
    (tmp_path / "idx.json").write_text("not valid json {")
    assert media_pipeline._load_index() == {}


# ---- attach_media: cache hit path (no network, no subprocess) ----


def test_attach_media_returns_cached_url(tmp_path, monkeypatch):
    """If the index already has an upload for this draft, skip download AND upload."""
    monkeypatch.setattr(media_pipeline, "_MEDIA_DIR", tmp_path)
    monkeypatch.setattr(media_pipeline, "_INDEX_PATH", tmp_path / "idx.json")
    media_pipeline._save_index({"117": "https://uploads.postiz.com/already.jpg"})

    # Patch _download + _postiz_upload to blow up if called — they shouldn't be.
    def _explode(*args, **kwargs):
        raise AssertionError("should not be called on cache hit")
    monkeypatch.setattr(media_pipeline, "_download", _explode)
    monkeypatch.setattr(media_pipeline, "_postiz_upload", _explode)

    url = media_pipeline.attach_media(117, "https://pbs.twimg.com/media/anything.jpg")
    assert url == "https://uploads.postiz.com/already.jpg"


def test_attach_media_force_bypasses_cache(tmp_path, monkeypatch):
    """With force=True, we should re-download + re-upload even if cached."""
    monkeypatch.setattr(media_pipeline, "_MEDIA_DIR", tmp_path)
    monkeypatch.setattr(media_pipeline, "_INDEX_PATH", tmp_path / "idx.json")
    media_pipeline._save_index({"117": "https://uploads.postiz.com/old.jpg"})

    calls = {"download": 0, "upload": 0}

    def fake_download(draft_id, source_url, *, force):
        calls["download"] += 1
        p = tmp_path / f"{draft_id}.jpg"
        p.write_bytes(b"fake")
        return p

    def fake_upload(path):
        calls["upload"] += 1
        return "https://uploads.postiz.com/new.jpg"

    monkeypatch.setattr(media_pipeline, "_download", fake_download)
    monkeypatch.setattr(media_pipeline, "_postiz_upload", fake_upload)

    url = media_pipeline.attach_media(117, "https://pbs.twimg.com/media/foo.jpg", force=True)
    assert url == "https://uploads.postiz.com/new.jpg"
    assert calls == {"download": 1, "upload": 1}
    # Cache should be updated too
    assert media_pipeline._load_index()["117"] == "https://uploads.postiz.com/new.jpg"


# ---- _postiz_upload timeout ----

def test_postiz_upload_uses_generous_timeout_for_videos(monkeypatch):
    """Regression guard: video uploads timed out at 120s, leaving drafts stuck
    at `scheduled`. The upload subprocess must use the raised _UPLOAD_TIMEOUT_SECONDS.
    """
    captured = {}

    class _Result:
        returncode = 0
        stdout = '{"path": "https://uploads.postiz.com/x.mp4"}'
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return _Result()

    monkeypatch.setattr(media_pipeline.subprocess, "run", fake_run)
    url = media_pipeline._postiz_upload(Path("/tmp/1234.mp4"))

    assert url == "https://uploads.postiz.com/x.mp4"
    assert captured["timeout"] == media_pipeline._UPLOAD_TIMEOUT_SECONDS
    # Must be materially larger than the old 120s that failed on real videos.
    assert media_pipeline._UPLOAD_TIMEOUT_SECONDS >= 300
