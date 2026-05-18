from unittest.mock import patch
from orbit.commands.setup import _setup_twitter
from orbit.config import Config

def test_setup_twitter_saves_cookies_path(tmp_path):
    cfg = Config(tmp_path)
    cookies_file = tmp_path / "x_cookies.txt"
    cookies_file.write_text("# Netscape HTTP Cookie File\n")

    with patch("orbit.commands.setup.Prompt.ask", return_value=str(cookies_file)):
        _setup_twitter(cfg)

    assert cfg.get("twitter.cookies_path") == str(cookies_file)

def test_setup_twitter_rejects_missing_file(tmp_path):
    cfg = Config(tmp_path)
    missing = str(tmp_path / "nonexistent.txt")

    with patch("orbit.commands.setup.Prompt.ask", return_value=missing):
        _setup_twitter(cfg)  # should print error, not raise

    assert cfg.get("twitter.cookies_path") is None
