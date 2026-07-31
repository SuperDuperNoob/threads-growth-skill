# Draft Quality Pipeline — Design

> Status: designed 2026-07-31. Not yet implemented.
> Author: Keith + Claude (brainstorming session).

## Problem

Threads drafts score 53–63 on the heuristic virality scorer with recurring
flags: "weak benefit," "no number," "soft hook," and — per Keith — they
sometimes **feel AI-written** and the **source tweets chosen are wrong**
(repetitive and/or too niche).

Root-cause narrowing (from brainstorming):

1. **Wrong tweets picked** is the #1 issue, and it happens BEFORE any draft is
   written. The current picker ranks bookmarks purely by cosine similarity to
   top-10 winner embeddings (`_rank_sources_by_similarity`). That objective is
   itself the problem:
   - **Repetition** — rewarding "similar to past winners" keeps mining the same
     clusters (Claude Code, open-source launches).
   - **Too niche** — cosine similarity has no concept of audience width; a
     deeply technical tweet sits close to a winner in vector space (shared
     vocabulary) while being too narrow to pop.
   The existing TOPIC FATIGUE GUARD and AUDIENCE WIDTH rules are bolt-on patches
   at *generation* time — they fire AFTER the ranker already chose the tweets.
   The fix is to promote that judgment UPSTREAM to source selection.

2. **Feels like AI / weak hooks** are text-side problems fixed AFTER a draft
   exists, via a critic + single refine pass.

## Non-goals (YAGNI)

- No refine-until-threshold loop. Research (self-refine / reflexion) shows the
  first critique→revision captures most gain; rounds 3–5 drift and over-sand
  the specificity that made a draft good. ONE refine pass only.
- No five-agent tower. The narrowing collapsed it to two stages.
- The LLM-calling wrappers are NOT unit-tested (they're I/O); only the pure
  prompt-builders, parsers, and selection logic are.

## Architecture

Two new pure-logic modules + wiring into `_run_draft_generation`
(`orbit/commands/draft.py`). Follows the repo's "pure functions + I/O wrapper"
convention (see `reports.py`, `embeddings.py`). LLM calls live in `draft.py`
(the I/O layer), matching how `build_pattern_prompt` is used today.

- `orbit/source_judge.py` — pure prompt-builder + parser for Stage 1.
- `orbit/critic.py` — pure prompt-builders + parsers + `pick_better()` for Stage 2.

### Stage 1 — Source Judge

Slots in at `draft.py:179`, right after `_rank_sources_by_similarity`,
replacing the raw top-20 slice.

- Embeddings still shortlist ~15 candidates (cheap, unchanged — coarse filter).
- ONE batched LLM call (Haiku) scores all 15 at once on three 0–10 axes:
  - **novelty** — penalize same brand/cluster as `recent_topics` (kills repetition)
  - **audience_width** — penalize researcher-niche / narrow dev-tool (kills too-niche)
  - **brand_fit** — reward the "general AI builder" sweet spot
- `total` blends the axes with **novelty weighted 1.5×** (Keith's #1 gripe).
- Returns strict JSON: `[{index, novelty, width, fit, total, reason}]`.
- Batched (not one-per-source) so the judge can compare across candidates —
  required for novelty ("these three are all Claude Code, keep the freshest").

Inputs are all already available at draft.py:179–187: `selected_sources`,
`recent_topics` (line 186), `top_patterns` (line 146).

Wiring:
```python
judged = judge_sources(ai_haiku, selected_sources, recent_topics, top_patterns)
if judged is not None:
    selected_sources = [selected_sources[j["index"]] for j in judged[:draft_count]]
# else: fall back to existing embedding order (graceful degrade)
```

### Stage 2 — Critic + Refine

Runs per-draft after `_parse_drafts` (draft.py:207), before the save loop.
Runs on ALL generated drafts. Applies in BOTH the JSON (Hermes) and interactive
paths so scheduled auto-posts get the same quality bar.

- **Critic call (Haiku)** — `build_critic_prompt(draft_text, top_patterns)`,
  grades 4 axes 0–10, each with a specific fix:
  - **hook** — line 1 leads with a surprising concrete result ("有人 + verb")
  - **payoff** — last line delivers a reader benefit, not an observation
  - **anti_slop** — reads human-written, not template-filled
  - **zh_naturalness** — native Traditional Chinese, not translated calques
  - Returns `{hook, payoff, anti_slop, zh_naturalness, total, fixes: [...]}`.
- **Refine call (Sonnet)**, only if `total < refine_threshold` (default 70) —
  `build_refine_prompt(draft_text, critique, top_patterns)` rewrites addressing
  ONLY flagged fixes, preserving what scored well.
- Re-critique the refined version. Keep whichever of {original, refined} scores
  higher via pure `pick_better(original, refined)`. One pass, no loop.

Guardrails:
1. **Critic is authoritative, not refiner** — never trust "refiner said better";
   re-grade and compare. Prevents reward-gaming.
2. **Fail-open everywhere** — errors keep the original draft; drafting never breaks.

## Error handling (fail-open)

| Failure | Behavior |
|---|---|
| Source-judge LLM error / bad JSON | Fall back to embedding ranking |
| Critic LLM error / bad JSON | Keep original draft, skip refine |
| Refine error | Keep original draft |
| Refine scores lower than original | Discard refine, keep original |
| `ANTHROPIC_API_KEY` missing | Handled upstream (draft.py:118) |

Each new LLM wrapper logs exceptions to stderr (VISIBLE, not silent — per the
sync-staleness lesson that dim failures hid an outage for ~3 weeks) and returns
`None` so callers degrade gracefully.

## Config (`~/.orbit/config.json`)

```json
"draft_quality": {
  "source_judge": true,
  "critic": true,
  "refine_threshold": 70,
  "novelty_weight": 1.5
}
```

Any stage can be disabled → falls back to today's behavior. Enables A/B and
spend control.

## Models

- **Judge + Critic** → `claude-haiku-4-5-20251001` (cheap, fast; fine for scoring)
- **Generation + Refine** → `claude-sonnet-4-6` (prose quality matters)

## Cost

Today: 1 LLM call/run. New worst case: 1 judge + up to 6 critic + up to 6 refine
+ 6 re-critique ≈ 13–19 calls, most on Haiku. A few cents/run — negligible for a
daily tool, but configurable.

## Testing

Matches repo pytest + pure-function convention. Existing 261 tests must pass
(new code is additive; fail-open keeps the old path reachable).

- `test_source_judge.py` — prompt includes all sources + recent topics; parser
  handles valid JSON, malformed JSON (→None), out-of-range indices, empty list.
- `test_critic.py` — prompt covers all 4 axes; parser validates score ranges,
  missing fields (→None); `pick_better(original, refined)` selection logic as a
  pure function (no LLM calls).

## Files touched

- NEW `orbit/source_judge.py`
- NEW `orbit/critic.py`
- EDIT `orbit/commands/draft.py` (wire both stages into `_run_draft_generation`)
- NEW `tests/test_source_judge.py`, `tests/test_critic.py`
- EDIT `CLAUDE.md` current-focus section + NAS mirror
