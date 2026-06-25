# project CLAUDE.md — threads-growth-skill / orbit

read this on every session in this repo. it captures non-obvious gotchas
that are not derivable from reading the codebase.

## project context

**name:** orbit (CLI inside the threads-growth-skill repo)

**what it is:** content flywheel CLI — pulls metrics from LinkedIn / YouTube
/ Threads into a local SQLite DB, generates Threads drafts from X bookmarks
using Claude Sonnet, and ranks bookmarks by embedding similarity to past
top-performing posts.

**target user:** keith (solo). not multi-user.

**current status:** in production on keith's own account. 81 Threads posts
tracked, embedding-based bookmark ranking shipped 2026-06-02.

## stack

- Python 3.14 (homebrew)
- typer + rich (CLI)
- sqlite-utils + SQLite at `~/.orbit/orbit.db`
- anthropic (Sonnet 4.6 for drafts), openai (text-embedding-3-large)
- httpx, twikit, youtube-transcript-api
- pytest

## environment gotchas — read before any dep change

- **orbit runs on homebrew Python 3.14**, NOT a venv. The `orbit` binary
  at `/opt/homebrew/bin/orbit` shebangs to
  `/opt/homebrew/opt/python@3.14/bin/python3.14`.
- **Installing new deps requires `--break-system-packages`** because
  homebrew Python is PEP 668-marked:
  `pip install --break-system-packages -e .`
- Auto-mode classifier will block that command by default. ask user
  for one-time approval.
- **`.venv/` exists at the repo root but is DEAD** — its shebang points
  to a path that no longer exists (repo was moved into `Workspaces/`).
  Don't try to use it. Don't recreate it without asking.

## test commands

- run full suite: `python -m pytest tests/`
- run one file: `python -m pytest tests/test_embeddings.py -v`
- 144 tests pass as of 2026-06-02. if a test fails, investigate root
  cause — don't just `assertEqual → assertAlmostEqual` your way past it
  (float32 round-trip precision IS a real concern for embeddings; bad
  test math is also a real concern — figure out which).

## draft pipeline — where each decision lives

knowing the file layout saves a lot of grep:

- **`orbit/commands/draft.py:_run_draft_generation(sources)`** — orchestrator.
  pulls top-10 Threads winners from DB with their embeddings, ranks
  incoming bookmarks by cosine similarity to winners, passes top-10 to
  the prompt builder.
- **`orbit/analysis.py:build_pattern_prompt(top_posts, bookmarks)`** — the
  ACTUAL prompt the LLM sees. THIS is the source of truth for hook
  templates, hard constraints, and "do not write" rules — NOT SKILL.md.
  refresh when post mix shifts.
- **`orbit/embeddings.py`** — OpenAI text-embedding-3-large (3072 dims).
  Vectors stored as BLOB on `posts.embedding` with `posts.embedding_model`
  tracking which model. Backfilled on every `orbit sync -p threads`.
  Bookmark score = MAX cosine similarity to any of top-10 winners.
- **`orbit/reports.py`** — pure renderer + I/O wrapper for
  `references/winning-formats.md`. Walks up from cwd to find skill root;
  silent no-op if run elsewhere.

## project-specific rules

- **never hand-edit `references/winning-formats.md`** — it's regenerated
  on every `orbit sync -p threads`. Your edits will be silently lost.
- **never hand-edit the prompt in `analysis.py:build_pattern_prompt`
  without also looking at the current top-30 by views in
  `references/winning-formats.md`.** Hard-coded claims like "6 of top-20
  are skill-launches" go stale fast.
- when adding a new embedding source/model, ALSO update
  `EMBEDDING_MODEL` in `orbit/embeddings.py`. Posts with mismatched
  model get re-embedded automatically on next sync.
- prefer pure functions + I/O wrappers (see `reports.py`, `embeddings.py`).
  Makes tests easy.
- don't pull in numpy. 4k dot products over 3072-dim floats is fast
  enough in pure Python at this scale.

## key files

- `SKILL.md` — workflow doc for the human (not the source of truth for
  the LLM prompt — see `analysis.py`)
- `references/winning-formats.md` — auto-generated performance report
- `~/.orbit/orbit.db` — SQLite store (posts, drafts, metrics, embeddings)
- `~/.orbit/config.json` — platform creds (linkedin, youtube, threads,
  twitter, anthropic)
- `~/.orbit/bookmarks_cache.json` — X bookmarks cache, refreshed via
  `orbit draft --refresh`
- `OPENAI_API_KEY` env var — required for embeddings, not stored in config

## current focus

**Threads slump-recovery (shipped 2026-06-03)** — 4 prompt-level changes in
`analysis.py:build_pattern_prompt`:

1. Template (d) DEPRECATED — skip unless pain is universal AND body
   resolves with a named tool. Was over-used (2 of last 7 = both <5k views).
2. AUDIENCE WIDTH rule — reject sources narrower than "general AI builder"
   (no researcher-only skills, niche dev-tool posts).
3. LAST LINE rule hardened — must be reader benefit, NOT observation.
   Observational endings ("這是新的預設", "AI 已經變了") are now in DO NOT WRITE.
4. TOPIC FATIGUE GUARD — `_run_draft_generation` queries last-5 posted
   topics from DB, passes to prompt. LLM rejects same brand/cluster.

Baseline to beat in 7 days: 5,380 median views (prior-14 before slump).

**LinkedIn format variety (shipped 2026-06-07)** — 5-format menu +
fatigue guard in `analysis.py:build_linkedin_prompt`. Diagnosis: ALL 8
recent LinkedIn posts classify as STORY format. LinkedIn's algo suppresses
repeated format from same author. Added FORMAT MENU with 5 options:

- **STORY** (the historical default — "After N, I [milestone]")
- **TEARDOWN** — analyze a public AI launch's wins/misses ("X shipped Y. Here's what they got right that Z missed")
- **CONTRARIAN** — flat assertion + evidence ("Most X is wrong about Y. 30-day audit: [number]")
- **RESOURCE DROP** — curated list ("I tested 12 X. The 4 worth using: [list]")
- **QUESTION→DATA** — specific question + measured answer

Wired:
- `build_linkedin_prompt(bookmarks, *, recent_formats=None)` — new kwarg
- `classify_linkedin_format(content)` — heuristic format detector
- `_format_fatigue_block(recent_formats)` — renders ban-list when ≥1 valid format
- `_recent_linkedin_formats(db, limit=3)` in `commands/draft.py` — queries
  recent linkedin drafts, classifies, passes to prompt
- `_maybe_generate_linkedin` now calls with `recent_formats=...`

Pre-fix: 8/8 recent LinkedIn drafts in DB classified as STORY → 6 sub-floor
posts. Post-fix: prompt forces selection of a non-recent format. Tests in
`test_linkedin_prompt.py` cover classifier + fatigue rendering (22 tests).

**LinkedIn slump-recovery v2 (hardened 2026-06-07)** — after 3 more
sub-400-impression posts slipped through the v1 rules (399, 222, 123 imp
on 6/4-6/7), `analysis.py:build_linkedin_prompt` got 4 additional rules:

1. **BAN-LIST patterns** — exact opener patterns auto-rejected:
   - "After N months/years of [X]" (duration span)
   - "N months/years ago I [X]" (TIME-AGO span — slipped 6/6 with 222 imp)
   - "For N months/years I [X]" (duration span — slipped 6/7 with 123 imp)
   - "Over the last [duration]"
2. **BRAG-FLEX REJECTION** — a countable number is not enough if it reads
   as a trophy. "After 149,000 views, I bought a Sony" (399 imp) framed
   the number as accomplishment without a struggle hook. Number must
   frame a PROBLEM/STRUGGLE/COUNTER-INTUITIVE realization.
3. **READER-BENEFIT-IN-FIRST-100-CHARS** — old checklist let LLM lead
   with autobiography and bury the insight at line 5+. New rule: the
   takeaway must be HINTED at in line 1-2, not buried.
4. **9-point checklist** (was 7) — added BRAG-FLEX check + reader-benefit
   check as explicit verification steps.

v1 changes (2026-06-03) still active: NUMBER-IN-HOOK rule, PERFORMANCE
FLOOR section (now lists 6 confirmed sub-floor posts), POSTING CADENCE
note (Tue/Thu 8-10am), DATA LIMITATION DISCLAIMER.

**Sync diagnosis + fixes (2026-06-14)** — investigated why LinkedIn/YouTube
data was frozen. The earlier "LinkedIn sync pulls impressions only — fix
get_metrics" framing was WRONG. Two separate root causes found by live-probing
the APIs (DB evidence: LinkedIn metrics frozen since 2026-05-26, YouTube since
2026-05-23):

1. **Both platforms had DEAD AUTH** — the actual reason data was stale:
   - LinkedIn: `401 DISABLED_APPLICATION` — the OAuth *app* is disabled in the
     LinkedIn Developer Portal. No code fix possible; re-enable the app, then
     `orbit setup --platform linkedin`.
   - YouTube: access token expired AND refresh token dead (`invalid_grant`).
     Re-auth via `orbit setup --platform youtube`. ALSO set the Google OAuth
     consent screen to "In production" (Testing-mode refresh tokens die in 7d).

2. **likes/comments=0 was NOT a mapping bug.** `linkedin.py:get_metrics` always
   mapped likeCount/commentCount correctly — but `shareStatistics` returns 0 for
   those on personal `urn:li:person:` authors (impressions+clicks are fine).
   The real counts live on `/v2/socialActions/{urn}`, which needs `r_member_social`
   scope (current app only has `w_member_social`; LinkedIn rarely grants read now).

Code shipped this session:
- **Staleness guard** (`commands/sync.py:_warn_if_stale` + pure
  `db.py:evaluate_staleness` / `last_metric_pull_per_platform`). Warns when a
  platform's newest metric is >3 days old (`STALE_AFTER_DAYS`). Also prints a
  LOUD persistent failure recap after the progress bar — a dim spinner line is
  how this outage went unnoticed for ~3 weeks. Never blocks. Tests:
  `test_sync_staleness.py`.
- **YouTube full-history pagination** (`platforms/youtube.py:get_videos` +
  `_list_video_ids`). Was silently capped at the most-recent 50; now follows
  `nextPageToken` up to `max_videos=500` (quota guard: search costs 100 units/page).
- **LinkedIn socialActions enrichment** (`platforms/linkedin.py:enrich_social_counts`).
  Backfills likes/comments per-URN (no batch endpoint). `_sync_linkedin` limits it
  to the **recent 50 posts** to avoid 700+ calls/sync. Degrades gracefully if the
  token lacks read scope (403 → keeps shareStatistics values, never lowers a count).
  Only verifiable once the LinkedIn app is re-enabled with r_member_social.

Next likely area: (a) confirm fresh data flows after Keith re-auths both,
(b) confirm socialActions actually returns nonzero likes (depends on whether the
re-enabled app gets r_member_social — if not, likes/comments stay 0 by platform
design, and analysis must keep using Excel exports).

**LinkedIn metric reversal: impressions → engagement rate (shipped 2026-06-26)** —
imported 7 fresh `SinglePostAnalytics` xlsx exports (real reactions/comments/saves,
which the API can't return for personal authors). The fresh data exposed that the
LinkedIn prompt was optimizing the WRONG metric:

- reach and engagement-rate are ANTICORRELATED in the data. The single highest-reach
  post (9,468 impressions) had 0.08% engagement; the best engagement rates (2.15%,
  2.11%, 2.48%) were all on posts under ~250 impressions.
- the OLD prompt's "PERFORMANCE FLOOR ~700 impressions" framing actively flagged
  Keith's HIGHEST-engagement posts as failures (e.g. "son drew a picture" = 202 imp
  but 2.48% eng; "wife stopped asking" = 521 imp but 1.34% eng — both ABOVE the
  re-derived 1.30% median).

`analysis.py:build_linkedin_prompt` changes:
1. PERFORMANCE FLOOR re-derived against REAL reaction data (n=20): median **1.30%**
   engagement, mean 1.56%, range 0.12%–3.47%. Floor to clear ≈ 1.0%.
2. inverted examples FIXED — the "failure" posts moved to the HIGH-engagement target
   list with an explicit "KEY REVERSAL" note so the LLM stops avoiding their patterns.
3. the 9,468-imp / 0.08% post is now the cautionary example (reach without resonance).
4. DATA LIMITATION note rewritten: engagement floor is fresh; hook/format content
   signals are STILL the stale May-2026 49-post set.
Tests: `test_linkedin_prompt.py` floor test reframed + new reach-vs-engagement
regression guard. 261 tests pass.

NOT done (blocked on data, not code): re-deriving WHICH hooks/formats drive
engagement. That needs post BODIES joined to engagement rate. **Gotcha discovered
this session:** the `Shares.csv` export (`orbit linkedin shares`) only backfills text
for posts that PREDATE the export. The 05-27-2026 export ends 2026-05-15; all 20
real-reaction posts are 2026-05-29 onward → ZERO overlap. To unblock: pull a FRESH
LinkedIn data export (must be newer than the latest tracked post), re-run
`orbit linkedin shares`, THEN content signals can be re-derived. Also note the URN
mismatch: `SinglePostAnalytics` filename URN ≠ in-URL activity URN ≠ Shares `ShareLink`
URN — don't expect a clean DB join across export types; join by date if needed.

## NAS mirror

a read-only copy of this CLAUDE.md lives in the obsidian vault at
`3. Resources/Claude/orbit/CLAUDE.md` for cross-machine reference. the
repo copy is the source of truth — when you edit, edit the repo file
and re-run the mirror command (see below).

mirror command (run after any CLAUDE.md edit):
```
cp CLAUDE.md "/Volumes/personal_folder/Obsidian/Obsidian/3. Resources/Claude/orbit/CLAUDE.md"
```
