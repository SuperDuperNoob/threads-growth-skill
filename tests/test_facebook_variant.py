"""Facebook-native cross-post variant (drafts handoff).

Facebook stopped getting the verbatim Threads clone — it gets a
discussion-framed rewrite. These tests pin the prompt contract and the
fail-open behavior of the rewrite helper (no network calls).
"""

from orbit.analysis import build_facebook_variant_prompt
from orbit.commands.drafts import _facebook_native


SAMPLE = "I automated my whole newsletter with 3 Claude agents. Took 2 hours."


def test_prompt_embeds_original_verbatim():
    prompt = build_facebook_variant_prompt(SAMPLE)
    assert SAMPLE in prompt


def test_prompt_pins_the_contract():
    prompt = build_facebook_variant_prompt(SAMPLE)
    # the parts that make it Facebook-native rather than a clone
    assert "ONE specific question" in prompt
    assert "invent nothing" in prompt
    assert "No hashtags" in prompt
    # output hygiene: bare post text only
    assert "Output ONLY the Facebook post text" in prompt


def test_facebook_native_fails_open_without_key(monkeypatch):
    """No API key → original content goes out (old behavior), with a warning."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    class NoKeyConfig:
        def get(self, _key, default=None):
            return default

    content, warning = _facebook_native(SAMPLE, NoKeyConfig())
    assert content == SAMPLE
    assert warning is not None and "verbatim cross-post" in warning


def test_facebook_native_fails_open_on_api_error(monkeypatch):
    """API blows up → original content goes out, warning names the failure."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")

    import anthropic

    class Boom:
        def __init__(self, **kwargs):
            raise RuntimeError("network down")

    monkeypatch.setattr(anthropic, "Anthropic", Boom)

    class NoKeyConfig:
        def get(self, _key, default=None):
            return default

    content, warning = _facebook_native(SAMPLE, NoKeyConfig())
    assert content == SAMPLE
    assert warning is not None and "rewrite failed" in warning
