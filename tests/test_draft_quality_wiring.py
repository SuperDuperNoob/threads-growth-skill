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


# --- happy-path wiring (valid JSON) ----------------------------------------

class _Resp:
    """Anthropic SDK response shape: `.content[0].text` is a string."""

    def __init__(self, text):
        self.content = [type("Blk", (), {"text": text})()]


def test_judge_sources_reorders_by_rank():
    # 3 sources; judge ranks index 2 best, then 0, then 1
    import json as _json
    payload = _json.dumps([
        {"index": 0, "novelty": 5, "width": 5, "fit": 5, "reason": "mid"},
        {"index": 1, "novelty": 1, "width": 1, "fit": 1, "reason": "low"},
        {"index": 2, "novelty": 9, "width": 9, "fit": 9, "reason": "top"},
    ])
    srcs = [{"text": "a"}, {"text": "b"}, {"text": "c"}]
    ai = FakeAI(lambda **k: _Resp(payload))
    cfgq = {"source_judge": True, "novelty_weight": 1.5}
    out = draft_mod._judge_sources(ai, srcs, [], [], cfgq, SilentStatus())
    assert [s["text"] for s in out] == ["c", "a", "b"]


def test_judge_sources_keeps_unjudged_sources_at_end():
    # only index 1 is judged; 0 and 2 must survive, in original order, after it
    import json as _json
    payload = _json.dumps([{"index": 1, "novelty": 9, "width": 9, "fit": 9, "reason": "x"}])
    srcs = [{"text": "a"}, {"text": "b"}, {"text": "c"}]
    ai = FakeAI(lambda **k: _Resp(payload))
    status = SilentStatus()
    cfgq = {"source_judge": True, "novelty_weight": 1.5}
    out = draft_mod._judge_sources(ai, srcs, [], [], cfgq, status)
    assert out[0]["text"] == "b"          # judged winner first
    assert {s["text"] for s in out} == {"a", "b", "c"}  # nothing dropped
    assert len(out) == 3
    assert status.messages                # warned about partial judging


def test_critique_and_refine_keeps_high_scoring_draft_without_refining():
    # critic returns total >= threshold -> no refine call, original returned
    import json as _json
    crit = _json.dumps({"hook": 9, "payoff": 9, "anti_slop": 9, "zh_naturalness": 9, "total": 90, "fixes": []})
    calls = {"n": 0}
    def on_create(**k):
        calls["n"] += 1
        return _Resp(crit)
    ai = FakeAI(on_create)
    cfgq = {"critic": True, "refine_threshold": 70}
    out = draft_mod._critique_and_refine(ai, "good draft", [], cfgq, SilentStatus())
    assert out == "good draft"
    assert calls["n"] == 1  # graded once, NOT refined (score above threshold)


def test_critique_and_refine_refines_and_keeps_better():
    # first grade low (total 40) -> refine -> re-grade high (total 88) -> keep refined
    import json as _json
    low = _json.dumps({"hook": 4, "payoff": 4, "anti_slop": 4, "zh_naturalness": 4, "total": 40, "fixes": ["x"]})
    high = _json.dumps({"hook": 8, "payoff": 8, "anti_slop": 8, "zh_naturalness": 8, "total": 88, "fixes": []})
    seq = iter([low, "refined draft text", high])  # grade, refine(returns text), re-grade
    ai = FakeAI(lambda **k: _Resp(next(seq)))
    cfgq = {"critic": True, "refine_threshold": 70}
    out = draft_mod._critique_and_refine(ai, "weak draft", [], cfgq, SilentStatus())
    assert out == "refined draft text"
