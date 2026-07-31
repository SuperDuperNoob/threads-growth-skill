# Draft Quality Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a two-stage LLM quality pass to Threads draft generation — a source-judge (fixes repetitive/niche tweet picks) and a critic+single-refine (fixes AI-feel and weak hooks).

**Architecture:** Two new pure-logic modules (`source_judge.py`, `critic.py`) holding prompt-builders + parsers + selection logic. LLM-calling wrappers live in `draft.py` (the I/O layer), matching how `build_pattern_prompt` is used today. Both stages fail-open: any error falls back to current behavior so drafting never breaks. Design doc: `docs/plans/2026-07-31-draft-quality-pipeline-design.md`.

**Tech Stack:** Python 3.14 (homebrew, NOT venv), pytest, `anthropic` SDK. Models: Haiku `claude-haiku-4-5-20251001` (judge/critic), Sonnet `claude-sonnet-4-6` (generation/refine). Run tests with `python -m pytest tests/`.

**Convention notes:**
- Pure functions + I/O wrapper (see `reports.py`, `embeddings.py`). Prompt-builders return plain f-strings like `analysis.py:build_pattern_prompt`.
- Fail-open + VISIBLE stderr logging (per the sync-staleness lesson: silent failures hid a 3-week outage).
- Frequent commits. TDD: failing test first.

---

### Task 1: Source-judge prompt builder

**Files:**
- Create: `orbit/source_judge.py`
- Test: `tests/test_source_judge.py`

**Step 1: Write failing test**

```python
# tests/test_source_judge.py
from orbit.source_judge import build_source_judge_prompt


def test_prompt_includes_every_source_and_recent_topics():
    sources = [
        {"author": "a", "url": "u1", "text": "Claude Code did X"},
        {"author": "b", "url": "u2", "text": "niche research paper Y"},
    ]
    recent = ["Claude Code migration story"]
    top = [{"content": "有人用 Claude Code...", "views": 190000, "like_rate": 1.1}]
    p = build_source_judge_prompt(sources, recent, top)
    # every source rendered with its index
    assert "[0]" in p and "[1]" in p
    assert "Claude Code did X" in p
    assert "niche research paper Y" in p
    # recent topics surfaced for the novelty axis
    assert "Claude Code migration story" in p
    # the three axes named
    assert "novelty" in p.lower()
    assert "audience" in p.lower() or "width" in p.lower()
    assert "fit" in p.lower()
    # instructs strict JSON array back
    assert "JSON" in p
```

**Step 2: Run to verify fail**

Run: `python -m pytest tests/test_source_judge.py -v`
Expected: FAIL — `ModuleNotFoundError: orbit.source_judge`

**Step 3: Minimal implementation**

```python
# orbit/source_judge.py
from __future__ import annotations
from typing import Any


def build_source_judge_prompt(
    sources: list[dict[str, Any]],
    recent_topics: list[str] | None,
    top_posts: list[dict[str, Any]],
) -> str:
    """Pure prompt: score each source on novelty/width/fit. Returns a string.

    The LLM is asked to return a strict JSON array of objects keyed by the
    source's zero-based index so the caller can map results back positionally.
    """
    rendered = "\n\n---\n\n".join(
        f"[{i}] Author: {s.get('author')}\n{s.get('text', '')}"
        for i, s in enumerate(sources)
    )
    recent = "\n".join(f"- {t}" for t in (recent_topics or [])[:5]) or "(none)"
    winners = "\n".join(f"- {p['content'][:80]}" for p in top_posts[:5])
    return f"""You are ranking candidate source tweets for Keith's Threads posts.
His audience: general AI builders. His best posts (for reference):
{winners}

RECENTLY POSTED TOPICS — anything covering the same brand/product/cluster as
these is LOW novelty; penalize hard:
{recent}

Score EACH candidate 0-10 on three axes:
- novelty: is this a fresh topic vs the recently-posted list? (repeats = 0-3)
- audience_width: does a GENERAL AI builder care, or is it researcher-niche /
  narrow dev-tooling? (too niche = 0-3)
- brand_fit: is it in Keith's "practical AI tool/launch" lane?

CANDIDATES:
{rendered}

Return ONLY a JSON array, one object per candidate:
[{{"index": 0, "novelty": 8, "width": 7, "fit": 9, "reason": "..."}}]
No prose outside the JSON."""
```

**Step 4: Run to verify pass**

Run: `python -m pytest tests/test_source_judge.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add orbit/source_judge.py tests/test_source_judge.py
git commit -m "feat: source-judge prompt builder"
```

---

### Task 2: Source-judge parser + weighted ranking

**Files:**
- Modify: `orbit/source_judge.py`
- Test: `tests/test_source_judge.py`

**Step 1: Write failing tests**

```python
from orbit.source_judge import parse_source_judgment, rank_judged


def test_parse_valid_json():
    raw = '[{"index":0,"novelty":8,"width":7,"fit":9,"reason":"fresh"}]'
    out = parse_source_judgment(raw)
    assert out == [{"index": 0, "novelty": 8, "width": 7, "fit": 9, "reason": "fresh"}]


def test_parse_tolerates_prose_around_json():
    raw = 'Here you go:\n[{"index":0,"novelty":5,"width":5,"fit":5,"reason":"x"}]\nDone'
    assert parse_source_judgment(raw)[0]["index"] == 0


def test_parse_bad_json_returns_none():
    assert parse_source_judgment("not json at all") is None
    assert parse_source_judgment("") is None


def test_parse_drops_out_of_range_or_malformed_entries():
    raw = '[{"index":0,"novelty":8,"width":7,"fit":9,"reason":"ok"},{"nope":1}]'
    out = parse_source_judgment(raw)
    assert len(out) == 1  # malformed entry dropped


def test_rank_weights_novelty_higher():
    # A: high novelty, mediocre others. B: low novelty, high others.
    judged = [
        {"index": 0, "novelty": 10, "width": 5, "fit": 5, "reason": "a"},
        {"index": 1, "novelty": 2, "width": 10, "fit": 10, "reason": "b"},
    ]
    ranked = rank_judged(judged, novelty_weight=1.5)
    # A total = 10*1.5 + 5 + 5 = 25 ; B = 2*1.5 + 10 + 10 = 23 -> A first
    assert ranked[0]["index"] == 0


def test_rank_default_weight_is_one():
    judged = [
        {"index": 0, "novelty": 6, "width": 5, "fit": 5, "reason": "a"},
        {"index": 1, "novelty": 5, "width": 6, "fit": 6, "reason": "b"},
    ]
    ranked = rank_judged(judged, novelty_weight=1.0)
    assert ranked[0]["index"] == 1  # 17 > 16
```

**Step 2: Run to verify fail**

Run: `python -m pytest tests/test_source_judge.py -v`
Expected: FAIL — `cannot import name 'parse_source_judgment'`

**Step 3: Implementation**

```python
import json


def parse_source_judgment(raw: str) -> list[dict] | None:
    """Parse the judge's JSON array. Returns None on any failure (fail-open).

    Drops entries missing required numeric axes or the index, so a partial
    response still yields usable rankings.
    """
    if not raw:
        return None
    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        data = json.loads(raw[start:end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    clean = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            clean.append({
                "index": int(item["index"]),
                "novelty": float(item["novelty"]),
                "width": float(item["width"]),
                "fit": float(item["fit"]),
                "reason": str(item.get("reason", "")),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return clean or None


def rank_judged(judged: list[dict], *, novelty_weight: float = 1.5) -> list[dict]:
    """Sort judged sources by weighted total, novelty weighted up by default."""
    def total(j: dict) -> float:
        return j["novelty"] * novelty_weight + j["width"] + j["fit"]
    return sorted(judged, key=total, reverse=True)
```

**Step 4: Run to verify pass**

Run: `python -m pytest tests/test_source_judge.py -v`
Expected: PASS (all Task 1 + Task 2 tests)

**Step 5: Commit**

```bash
git add orbit/source_judge.py tests/test_source_judge.py
git commit -m "feat: source-judge parser + novelty-weighted ranking"
```

---

### Task 3: Critic prompt builder + parser

**Files:**
- Create: `orbit/critic.py`
- Test: `tests/test_critic.py`

**Step 1: Write failing tests**

```python
# tests/test_critic.py
from orbit.critic import build_critic_prompt, parse_critique


def test_critic_prompt_names_four_axes_and_the_draft():
    p = build_critic_prompt("有人開源了一個工具。\n免費。", top_posts=[])
    assert "有人開源了一個工具" in p
    for axis in ("hook", "payoff", "slop", "chinese"):
        assert axis in p.lower()
    assert "JSON" in p


def test_parse_valid_critique():
    raw = '{"hook":8,"payoff":6,"anti_slop":7,"zh_naturalness":9,"total":30,"fixes":["tighten last line"]}'
    c = parse_critique(raw)
    assert c["total"] == 30
    assert c["fixes"] == ["tighten last line"]


def test_parse_computes_total_when_missing():
    raw = '{"hook":8,"payoff":6,"anti_slop":7,"zh_naturalness":9,"fixes":[]}'
    c = parse_critique(raw)
    assert c["total"] == 30  # summed from the four axes


def test_parse_bad_json_returns_none():
    assert parse_critique("garbage") is None
    assert parse_critique("") is None


def test_parse_missing_axis_returns_none():
    assert parse_critique('{"hook":8,"payoff":6}') is None
```

**Step 2: Run to verify fail**

Run: `python -m pytest tests/test_critic.py -v`
Expected: FAIL — `ModuleNotFoundError: orbit.critic`

**Step 3: Implementation**

```python
# orbit/critic.py
from __future__ import annotations
import json
from typing import Any

_AXES = ("hook", "payoff", "anti_slop", "zh_naturalness")


def build_critic_prompt(draft: str, top_posts: list[dict[str, Any]]) -> str:
    ref = "\n".join(f"- {p['content'][:80]}" for p in (top_posts or [])[:3])
    return f"""You grade a single Threads draft for Keith (audience: AI builders).
Reference winners:
{ref or "(none)"}

Grade the draft 0-10 on FOUR axes:
- hook: does line 1 lead with a surprising, concrete result? ("有人 + verb + named tool")
- payoff: does the LAST line deliver a reader benefit, not a flat observation?
- anti_slop: does it read human-written, or like template-filled AI slop?
- chinese (zh_naturalness): is it native Traditional Chinese, not translated-from-English calques?

DRAFT:
{draft}

Return ONLY JSON:
{{"hook":N,"payoff":N,"anti_slop":N,"zh_naturalness":N,"total":N,"fixes":["specific fix", ...]}}
`fixes` = concrete, minimal edits to raise the lowest axes. No prose outside JSON."""


def parse_critique(raw: str) -> dict | None:
    """Parse critic JSON. None on failure or any missing axis (fail-open)."""
    if not raw:
        return None
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        data = json.loads(raw[start:end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        scores = {axis: float(data[axis]) for axis in _AXES}
    except (KeyError, TypeError, ValueError):
        return None
    total = data.get("total")
    try:
        total = float(total)
    except (TypeError, ValueError):
        total = sum(scores.values())
    fixes = data.get("fixes") or []
    if not isinstance(fixes, list):
        fixes = []
    return {**scores, "total": total, "fixes": [str(f) for f in fixes]}
```

**Step 4: Run to verify pass**

Run: `python -m pytest tests/test_critic.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add orbit/critic.py tests/test_critic.py
git commit -m "feat: critic prompt builder + parser"
```

---

### Task 4: Refine prompt + pick_better selection

**Files:**
- Modify: `orbit/critic.py`
- Test: `tests/test_critic.py`

**Step 1: Write failing tests**

```python
from orbit.critic import build_refine_prompt, pick_better


def test_refine_prompt_includes_draft_and_fixes():
    crit = {"hook": 4, "payoff": 3, "anti_slop": 6, "zh_naturalness": 8,
            "total": 21, "fixes": ["lead with the number", "cut the last line"]}
    p = build_refine_prompt("原始草稿內容", crit, top_posts=[])
    assert "原始草稿內容" in p
    assert "lead with the number" in p
    assert "cut the last line" in p


def test_pick_better_returns_higher_scoring():
    original = ("orig text", {"total": 60})
    refined = ("refined text", {"total": 75})
    text, crit = pick_better(original, refined)
    assert text == "refined text"


def test_pick_better_prefers_original_on_tie_or_lower():
    original = ("orig", {"total": 70})
    refined = ("worse", {"total": 65})
    assert pick_better(original, refined)[0] == "orig"
    # tie -> keep original (refine must strictly beat it)
    assert pick_better(("orig", {"total": 70}), ("ref", {"total": 70}))[0] == "orig"


def test_pick_better_handles_none_refined():
    original = ("orig", {"total": 55})
    assert pick_better(original, None)[0] == "orig"
```

**Step 2: Run to verify fail**

Run: `python -m pytest tests/test_critic.py -v`
Expected: FAIL — `cannot import name 'build_refine_prompt'`

**Step 3: Implementation**

```python
def build_refine_prompt(draft: str, critique: dict, top_posts: list[dict[str, Any]]) -> str:
    fixes = "\n".join(f"- {f}" for f in critique.get("fixes", [])) or "- tighten the hook and payoff"
    ref = "\n".join(f"- {p['content'][:80]}" for p in (top_posts or [])[:3])
    return f"""Rewrite this Threads draft addressing ONLY these critic fixes:
{fixes}

Preserve what already works. Keep it Traditional Chinese, under 500 chars,
same core topic. Reference winners for tone:
{ref or "(none)"}

ORIGINAL DRAFT:
{draft}

Return ONLY the rewritten draft text. No preamble, no JSON, no commentary."""


def pick_better(
    original: tuple[str, dict],
    refined: tuple[str, dict] | None,
) -> tuple[str, dict]:
    """Keep whichever draft scores higher. Refine must STRICTLY beat original.

    Each arg is (text, critique_dict). `refined` may be None (refine skipped or
    failed) -> original wins. This is the guardrail against reward-gaming: the
    refiner's own opinion never counts, only the re-graded critic total.
    """
    if refined is None:
        return original
    if refined[1].get("total", 0) > original[1].get("total", 0):
        return refined
    return original
```

**Step 4: Run to verify pass**

Run: `python -m pytest tests/test_critic.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add orbit/critic.py tests/test_critic.py
git commit -m "feat: refine prompt + pick_better selection guard"
```

---

### Task 5: Config accessors with safe defaults

**Files:**
- Modify: `orbit/source_judge.py` (add `quality_config` helper OR put in a small `orbit/quality.py` — choose whichever keeps imports clean)
- Test: `tests/test_source_judge.py` (or `tests/test_quality_config.py`)

**Step 1: Write failing test**

```python
from orbit.source_judge import quality_config


def test_quality_config_defaults_when_absent():
    cfg = quality_config({})
    assert cfg["source_judge"] is True
    assert cfg["critic"] is True
    assert cfg["refine_threshold"] == 70
    assert cfg["novelty_weight"] == 1.5


def test_quality_config_respects_overrides():
    raw = {"draft_quality": {"source_judge": False, "refine_threshold": 80}}
    cfg = quality_config(raw)
    assert cfg["source_judge"] is False
    assert cfg["refine_threshold"] == 80
    assert cfg["critic"] is True  # untouched default
```

**Step 2: Run to verify fail** → `cannot import name 'quality_config'`

**Step 3: Implementation**

```python
_QUALITY_DEFAULTS = {
    "source_judge": True,
    "critic": True,
    "refine_threshold": 70,
    "novelty_weight": 1.5,
}


def quality_config(raw_config: dict) -> dict:
    """Merge `draft_quality` overrides onto safe defaults. Pure."""
    user = (raw_config or {}).get("draft_quality") or {}
    return {**_QUALITY_DEFAULTS, **{k: user[k] for k in _QUALITY_DEFAULTS if k in user}}
```

**Step 4: Run to verify pass**

**Step 5: Commit**

```bash
git commit -am "feat: draft_quality config accessor with safe defaults"
```

---

### Task 6: Wire Stage 1 (source-judge) into draft.py

**Files:**
- Modify: `orbit/commands/draft.py` (imports at top; insert after line 179 `_require_media_sources`, before `recent_topics` query at 186 — NOTE: judge needs `recent_topics`, so query recent_topics BEFORE the judge call; move line 186 up if needed)

**Step 1: Add the I/O wrapper function near the other draft helpers**

```python
def _judge_sources(ai, sources, recent_topics, top_patterns, cfg_quality, status):
    """LLM re-rank of shortlisted sources. Fail-open to input order."""
    if not cfg_quality["source_judge"] or not sources:
        return sources
    from orbit.source_judge import build_source_judge_prompt, parse_source_judgment, rank_judged
    try:
        prompt = build_source_judge_prompt(sources, recent_topics, top_patterns)
        msg = ai.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        judged = parse_source_judgment(msg.content[0].text)
    except Exception as e:  # noqa: BLE001 - fail-open, log visibly
        status.print(f"[yellow]⚠ Source judge failed ({e}); using embedding order.[/yellow]")
        return sources
    if not judged:
        status.print("[yellow]⚠ Source judge returned nothing; using embedding order.[/yellow]")
        return sources
    ranked = rank_judged(judged, novelty_weight=cfg_quality["novelty_weight"])
    reordered = [sources[j["index"]] for j in ranked if 0 <= j["index"] < len(sources)]
    return reordered or sources
```

**Step 2: Wire it in.** After `selected_sources = _require_media_sources(...)` (line 179) and after `recent_topics`/`top_patterns` exist, add:

```python
    ai = anthropic.Anthropic(api_key=api_key)  # if not already constructed above
    cfg_quality = quality_config(cfg.data if hasattr(cfg, "data") else {})  # adapt to Config's accessor
    selected_sources = _judge_sources(
        ai, selected_sources, recent_topics, top_patterns, cfg_quality, status,
    )
```

NOTE: `recent_topics` is queried at line 186 — move that query ABOVE this call. Verify how `Config` exposes raw dict (check `orbit/config.py`); use the correct accessor for `quality_config`.

**Step 3: Manual smoke (no live API needed)** — run the full suite to prove nothing broke:

Run: `python -m pytest tests/ -q`
Expected: 261+ pass (existing behavior unchanged when judge disabled or fails).

**Step 4: Commit**

```bash
git commit -am "feat: wire source-judge (Stage 1) into draft generation, fail-open"
```

---

### Task 7: Wire Stage 2 (critic+refine) into draft.py

**Files:**
- Modify: `orbit/commands/draft.py` (add wrapper; call it on each parsed draft after line 207 `_parse_drafts`, before the save loops)

**Step 1: Add the wrapper**

```python
def _critique_and_refine(ai, draft_text, top_patterns, cfg_quality, status):
    """Grade a draft; refine once if below threshold; return the better text.

    Fail-open: any error returns the original draft unchanged.
    """
    if not cfg_quality["critic"]:
        return draft_text
    from orbit.critic import build_critic_prompt, parse_critique, build_refine_prompt, pick_better

    def _grade(text):
        try:
            msg = ai.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=512,
                messages=[{"role": "user", "content": build_critic_prompt(text, top_patterns)}],
            )
            return parse_critique(msg.content[0].text)
        except Exception as e:  # noqa: BLE001
            status.print(f"[yellow]⚠ Critic failed ({e}); keeping draft as-is.[/yellow]")
            return None

    original_crit = _grade(draft_text)
    if original_crit is None:
        return draft_text
    if original_crit["total"] >= cfg_quality["refine_threshold"]:
        return draft_text
    # Below threshold: one refine pass (Sonnet), then re-grade and keep better.
    try:
        rmsg = ai.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": build_refine_prompt(draft_text, original_crit, top_patterns)}],
        )
        refined_text = rmsg.content[0].text.strip()
    except Exception as e:  # noqa: BLE001
        status.print(f"[yellow]⚠ Refine failed ({e}); keeping original.[/yellow]")
        return draft_text
    refined_crit = _grade(refined_text)
    better, _ = pick_better((draft_text, original_crit),
                            (refined_text, refined_crit) if refined_crit else None)
    return better
```

**Step 2: Apply to each parsed draft.** Right after `drafts = _parse_drafts(raw)` and the empty-check (line ~212), add:

```python
    drafts = [
        _critique_and_refine(ai, d, top_patterns, cfg_quality, status)
        for d in drafts
    ]
```

This runs in BOTH json and interactive paths (both use `drafts` downstream). Confirm `draft_sources` matching (line 219) still works — it matches by token overlap against source text, which is unaffected by refinement (topic preserved). If a refined draft no longer matches its source well, `_best_source_match` falls back positionally — acceptable.

**Step 3: Run full suite**

Run: `python -m pytest tests/ -q`
Expected: all pass. Existing draft tests should be unaffected (they either don't hit this path or mock the AI client — verify; if a test calls `_run_draft_generation` with a real-ish flow, it may need the critic disabled via config or a mocked client).

**Step 4: Commit**

```bash
git commit -am "feat: wire critic+refine (Stage 2) into draft generation, fail-open"
```

---

### Task 8: Full regression + config-off verification

**Step 1:** `python -m pytest tests/ -q` — all green (target 261 + new tests, ~275+).

**Step 2: Verify fail-open path with a stub.** Add a test that calls `_judge_sources` / `_critique_and_refine` with a fake `ai` whose `messages.create` raises, and asserts the input is returned unchanged. (Put in `tests/test_draft_quality_wiring.py`.)

```python
def test_judge_sources_fails_open(monkeypatch):
    from orbit.commands import draft as d
    class BoomAI:
        class messages:
            @staticmethod
            def create(**k): raise RuntimeError("boom")
    srcs = [{"author": "a", "url": "u", "text": "t"}]
    cfgq = {"source_judge": True, "critic": True, "refine_threshold": 70, "novelty_weight": 1.5}
    class S:  # silent status
        def print(self, *a, **k): pass
    out = d._judge_sources(BoomAI(), srcs, [], [], cfgq, S())
    assert out == srcs  # unchanged on failure
```

**Step 3: Commit**

```bash
git commit -am "test: fail-open wiring tests for draft quality stages"
```

---

### Task 9: Docs — CLAUDE.md current-focus + NAS mirror

**Files:**
- Modify: `CLAUDE.md` (add a "Draft quality pipeline (shipped YYYY-MM-DD)" block under current focus, describing both stages, the config keys, fail-open, and the new files)
- Run NAS mirror command from CLAUDE.md (only if `/Volumes/personal_folder` is mounted; else note it must be re-run later)

**Step 1:** Write the current-focus entry (mirror the style of existing entries: what shipped, why, files wired, tests count).

**Step 2:** Commit.

```bash
git commit -am "docs: CLAUDE.md draft quality pipeline entry"
```

**Step 3:** Mirror: `cp CLAUDE.md "/Volumes/personal_folder/Obsidian/Obsidian/3. Resources/Claude/orbit/CLAUDE.md"` (skip + flag if unmounted).

---

## Verification checklist (before finishing branch)

- [ ] `python -m pytest tests/` all green
- [ ] Source judge disabled via config → embedding order preserved (test)
- [ ] Critic disabled via config → drafts pass through unchanged (test)
- [ ] Every LLM wrapper fails open with a VISIBLE stderr warning (tests)
- [ ] `pick_better` never returns refined unless it strictly beats original
- [ ] No numpy imported; no new deps (uses existing `anthropic`)
- [ ] CLAUDE.md updated + mirrored
- [ ] Confirm `Config` raw-dict accessor used by `quality_config` is correct (read `orbit/config.py`)

## Open implementation risks (resolve during coding)

1. **`Config` raw access** — RESOLVED: `orbit/config.py` stores the raw dict as `self._data` and exposes a dotted `get(key)`. `quality_config` takes a plain dict, so in Task 6 call it as `quality_config(cfg._data)` (the test in Task 5 already passes a plain dict, so no test change needed). Do NOT add a new public accessor — `_data` is fine for an internal helper in the same package.
2. **Existing draft tests may construct a real `anthropic.Anthropic`** — if any test exercises `_run_draft_generation` end-to-end, adding two more `messages.create` calls could break mocks. Check `tests/` for how the AI client is stubbed; the new wrappers must respect the same stub.
3. **Latency** — up to ~13-19 calls/run. Not a correctness issue, but note in CLAUDE.md so the Hermes headless run's timeout accounts for it.
