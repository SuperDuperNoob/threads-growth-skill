"""Fail-open regression tests for the draft-quality wiring.

These pin down the already-implemented fail-open behavior of the two
quality stages in `orbit.commands.draft` so it can't silently regress:

- `_judge_sources`  — LLM re-rank of shortlisted sources
- `_critique_and_refine` — grade-then-refine a draft

Both stages MUST fail open: if the quality flag is off, or the LLM call
raises, the caller gets back the original input unchanged and no crash
propagates.
"""
from orbit.commands import draft as draft_mod


# --- fakes -----------------------------------------------------------------

class SilentStatus:
    """Stand-in for the rich Console; swallows every warning print."""

    def __init__(self):
        self.messages = []

    def print(self, *args, **kwargs):
        # Record so tests may (optionally) assert a warning was emitted.
        self.messages.append(args[0] if args else "")


class _Messages:
    def __init__(self, on_create):
        self._on_create = on_create

    def create(self, **kwargs):
        return self._on_create(**kwargs)


class FakeAI:
    """Minimal anthropic-client shape: `ai.messages.create(**kwargs)`."""

    def __init__(self, on_create):
        self.messages = _Messages(on_create)


def _raise(**kwargs):
    raise RuntimeError("boom")


def _must_not_call(**kwargs):
    raise AssertionError("ai.messages.create should not be called")


SOURCES = [
    {"author": "alice", "url": "u1", "text": "t1"},
    {"author": "bob", "url": "u2", "text": "t2"},
]


# --- _judge_sources --------------------------------------------------------

def test_judge_sources_fails_open_on_exception():
    """LLM call raises -> return input sources unchanged (contents + order)."""
    ai = FakeAI(_raise)
    status = SilentStatus()
    cfg_quality = {"source_judge": True, "novelty_weight": 0.5}

    result = draft_mod._judge_sources(
        ai, SOURCES, recent_topics=[], top_patterns=[], cfg_quality=cfg_quality, status=status
    )

    assert result == SOURCES
    assert result is SOURCES  # the original object, not a reordered copy
    assert status.messages, "a warning should be printed on the fail-open path"


def test_judge_sources_short_circuits_when_disabled():
    """source_judge falsy -> no LLM call, sources returned unchanged."""
    ai = FakeAI(_must_not_call)
    status = SilentStatus()
    cfg_quality = {"source_judge": False, "novelty_weight": 0.5}

    result = draft_mod._judge_sources(
        ai, SOURCES, recent_topics=[], top_patterns=[], cfg_quality=cfg_quality, status=status
    )

    assert result is SOURCES  # would have raised AssertionError if create() ran


def test_judge_sources_empty_sources_returns_empty():
    """Empty sources -> empty out, no crash, no LLM call even when enabled."""
    ai = FakeAI(_must_not_call)
    status = SilentStatus()
    cfg_quality = {"source_judge": True, "novelty_weight": 0.5}

    result = draft_mod._judge_sources(
        ai, [], recent_topics=[], top_patterns=[], cfg_quality=cfg_quality, status=status
    )

    assert result == []


# --- _critique_and_refine --------------------------------------------------

def test_critique_and_refine_fails_open_on_critic_exception():
    """Critic grade call raises -> return original draft_text unchanged."""
    ai = FakeAI(_raise)
    status = SilentStatus()
    cfg_quality = {"critic": True, "refine_threshold": 80}
    draft_text = "the original draft body"

    result = draft_mod._critique_and_refine(
        ai, draft_text, top_patterns=[], cfg_quality=cfg_quality, status=status
    )

    assert result == draft_text
    assert status.messages, "a warning should be printed when the critic fails"


def test_critique_and_refine_short_circuits_when_disabled():
    """critic falsy -> no LLM call, draft_text returned unchanged."""
    ai = FakeAI(_must_not_call)
    status = SilentStatus()
    cfg_quality = {"critic": False, "refine_threshold": 80}
    draft_text = "the original draft body"

    result = draft_mod._critique_and_refine(
        ai, draft_text, top_patterns=[], cfg_quality=cfg_quality, status=status
    )

    assert result == draft_text  # would have raised AssertionError if create() ran
