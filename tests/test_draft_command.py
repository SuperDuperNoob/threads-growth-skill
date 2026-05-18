from unittest.mock import patch, MagicMock
from typer.testing import CliRunner
from orbit.cli import app

runner = CliRunner()

def test_draft_exits_if_twitter_not_configured():
    with patch("orbit.commands.draft.Config") as MockConfig:
        instance = MockConfig.return_value
        instance.get.return_value = None
        result = runner.invoke(app, ["draft"])
    assert result.exit_code != 0 or "not configured" in result.output.lower()

def test_draft_exits_if_anthropic_key_missing():
    with patch("orbit.commands.draft.Config") as MockConfig, \
         patch.dict("os.environ", {}, clear=True):
        instance = MockConfig.return_value
        instance.get.side_effect = lambda k: "fake_path" if "twitter" in k else None
        result = runner.invoke(app, ["draft"])
    assert result.exit_code != 0 or "anthropic" in result.output.lower()

def test_parse_drafts_splits_numbered_sections():
    from orbit.commands.draft import _parse_drafts
    text = "[1]\nFirst draft content\n\n[2]\nSecond draft content\n\n[3]\nThird draft"
    drafts = _parse_drafts(text)
    assert len(drafts) == 3
    assert "First draft content" in drafts[0]
    assert "Second draft content" in drafts[1]

def test_parse_drafts_handles_missing_sections():
    from orbit.commands.draft import _parse_drafts
    text = "[1]\nOnly one draft"
    drafts = _parse_drafts(text)
    assert len(drafts) == 1
