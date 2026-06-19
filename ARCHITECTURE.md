# Orbit — Architecture

A guide for anyone reading this codebase for the first time. Read this before
diving into the source. For day-to-day gotchas (Python env, test commands,
project-specific rules) see [`CLAUDE.md`](CLAUDE.md).

> **Note:** the top-level `README.md` describes an older "Hermes skill that
> scrapes Threads via shell scripts." That is historical. The live system is the
> `orbit` Python CLI documented here.

---

## What Orbit is

Orbit is a **content flywheel CLI** for a solo creator (Keith). It:

1. **Syncs** real performance metrics (views/likes/comments) from LinkedIn,
   YouTube, and Threads into a local SQLite DB.
2. **Discovers / drafts** new Threads posts — from X bookmarks *or* the X "For
   You" feed — by ranking candidates against the creator's own top-performing
   posts (embedding similarity) and feeding them to Claude with a
   data-tuned prompt.
3. **Schedules** finished drafts to Threads + Facebook (and LinkedIn) via
   [Postiz](https://postiz.com).

The guiding principle: **post by your own data, not generic best practice.** Every
draft is generated from patterns learned off the creator's measured winners.

---

## The big picture

```
                      ┌──────────────────────────────────────────┐
                      │           ~/.orbit/  (ORBIT_HOME)          │
                      │  config.json · orbit.db · bookmarks_cache  │
                      └──────────────────────────────────────────┘
                                        ▲
        sync metrics                    │                 generate drafts
   ┌───────────────────┐        ┌───────┴────────┐      ┌──────────────────┐
   │ platforms/         │  ───▶  │   orbit.db     │ ◀──  │ analysis.py       │
   │  threads/linkedin/ │        │  (SQLite via   │      │  (the LLM prompt) │
   │  youtube/twitter   │        │   sqlite-utils)│      │ embeddings.py     │
   └───────────────────┘        └───────┬────────┘      │ duplicates.py     │
                                        │                └──────────────────┘
                                        ▼                          │
                                ┌───────────────┐                  ▼
                                │ platforms/    │           Claude (Sonnet)
                                │  postiz.py    │  ◀── schedule drafts
                                └───────────────┘
```

Three components, loosely coupled, all mediated by the SQLite DB.

---

## Layout

### Entry point
- **`orbit/cli.py`** — the Typer app. Registers every sub-command
  (`add_typer`). `orbit threads` is an alias for `orbit draft`. The root
  callback shows the splash and, with no subcommand, an interactive menu.

### Commands (`orbit/commands/`) — one Typer app per file
| Command | What it does |
|---------|--------------|
| `setup` | One-time per-platform credential setup → `config.json` |
| `sync` | Pull metrics from a platform into `metrics`/`posts`. Has a **staleness guard** that warns when a platform's newest metric is >3 days old. |
| `status` | Show DB state at a glance |
| `insights` | Top posts + engagement summaries |
| `draft` (`threads`) | **Draft from X bookmarks.** `--json` = headless (Hermes). |
| `drafts` | Manage saved drafts: `list/show/publish/handoff/comment/schedule/due` |
| `discover` | **Draft from your X "For You" feed.** Scores candidates, then `discover draft N,M` / `discover autofill`. `--json` headless. |
| `interview` | Turn the creator's own experiments into drafts |
| `repurpose` | Turn a YouTube video into drafts |
| `youtube` | Jeff-Sue-style video production checklist |
| `linkedin` | Import LinkedIn analytics/single-post exports (API sync is dead — see CLAUDE.md) |

### Core logic (`orbit/`)
| Module | Responsibility |
|--------|----------------|
| **`analysis.py`** | **Builds the actual LLM prompt** (`build_pattern_prompt`, `build_linkedin_prompt`). This is the source of truth for hook templates, hard constraints, and "do not write" rules — *not* SKILL.md. Heavily data-tuned; see the dated comments. |
| **`embeddings.py`** | OpenAI `text-embedding-3-large` (3072-dim). Ranks bookmarks by MAX cosine similarity to the creator's top-10 winners. Vectors stored as BLOB on `posts.embedding`. |
| **`duplicates.py`** | Hard dedup. Blocks a candidate only if it's the same tweet, same canonical URL, a shared *distinctive* product name, or near-identical wording — **not** merely the same brand/topic. |
| **`discovery.py`** | Audience-fit scoring for feed tweets (brand mentions, open-source signal, freshness, engagement, novelty). |
| **`scheduling.py`** | Generates the HKT 9am/4pm/9pm posting slots. |
| **`media_pipeline.py`** | Downloads X media, re-uploads to Postiz so posts carry Postiz-hosted media. |
| **`reports.py`** | Renders `references/winning-formats.md` (auto-generated — never hand-edit). |
| **`db.py`** | Thin wrapper over `sqlite-utils`. |
| **`paths.py`** | Resolves `ORBIT_HOME` (defaults to `~/.orbit`; overridable for the shared-NAS Hermes setup). |
| **`locking.py`** | Single-writer file lock for the shared NAS-hosted home (Hermes safety). |
| **`config.py`** | `config.json` accessor (`cfg.get("twitter.cookies_path")` dotted keys). |
| **`curated.py`** | Curated X accounts to mine for candidates. |
| **`github_link.py`** | Resolves the GitHub repo behind a project mentioned in a draft. |
| **`splash.py`** | ASCII banner. Static (non-TTY) splash prints to **stderr** so `--json` stdout stays pure. |

### Platform adapters (`orbit/platforms/`)
`threads.py`, `linkedin.py`, `youtube.py`, `twitter.py` (twikit-based, fragile),
`postiz.py` (scheduling), `meta_token.py`, `linkedin_cm.py`,
`youtube_transcript.py`. Each isolates one external API.

---

## The draft pipeline (most important flow)

This is where new content is born. Entry: `commands/draft.py:_run_draft_generation(sources)`.

1. **Gather sources** — X bookmarks (`draft`) or ranked feed picks (`discover draft`).
2. **Filter dismissed** — drop sources the creator marked "done" (ground truth beats guessing).
3. **Hard dedup** (`duplicates.py`) — drop already-covered sources.
4. **Dedupe against published** — drop news already posted about.
5. **Rank by similarity** (`embeddings.py`) — cosine similarity to top-10 winners.
6. **Require media** — Threads posts must be image/video-backed (returns the
   media-backed subset; caller emits empty JSON rather than crashing if none).
7. **Build the prompt** (`analysis.py:build_pattern_prompt`) — injects top
   posts as examples, recent-topic fatigue guard, recent-performance recovery
   mode, and the diversity plan.
8. **Call Claude** (Sonnet) → parse drafts → score virality → save to `drafts`.
9. **Interactive mode:** present a picker (save/tweak/regen/dismiss).
   **`--json` mode:** save all, print `{"candidates": [...]}` to stdout, exit 0.
   `--json` is what the headless Hermes agent consumes — stdout is *only* JSON,
   all chatter goes to stderr.

**To change what the LLM writes, edit `analysis.py` — not `SKILL.md`.** Always
cross-check against the current top-30 in `references/winning-formats.md` first;
the prompt contains hard-coded performance claims that go stale.

---

## Data model (`~/.orbit/orbit.db`)

| Table | Holds |
|-------|-------|
| `posts` | Published posts per platform + `embedding` BLOB |
| `metrics` | Time-series metric pulls (`pulled_at`) per post |
| `drafts` | Generated/saved drafts (`status`: draft → scheduled → handed_off_to_postiz → published) |
| `ideas` | Parent record for a draft (title/source/status) |
| `discoveries` | Scored feed candidates (`status`: new → drafted) |
| `content_ledger` | Dedup fingerprints for committed content |
| `dismissed_sources` | Sources the creator told us to stop offering |
| `youtube_*` | Video production checklists |

`config.json` holds platform creds; `OPENAI_API_KEY` is an **env var**, not in config.

---

## Headless mode (Hermes auto-posting)

Orbit runs unattended from a shared NAS by the Hermes agent:
- `ORBIT_HOME` points at the shared home; `locking.py` serializes writes.
- `orbit draft --json` / `orbit discover draft --json` generate+save+emit JSON.
- `orbit drafts schedule <id>` hands a draft to Postiz; prints JSON, exits 0/non-0.
- **stdout purity matters** — the agent parses stdout as JSON, so the splash and
  all status text go to stderr. Never wrap a posting command in a shell retry
  (it double-posts); run once, parse the saved output separately.

See [`hermes-orbit-runbook.md`](hermes-orbit-runbook.md) for operational steps.

---

## Stack & conventions

- Python 3.14 (homebrew, **not** a venv), Typer + Rich, sqlite-utils, anthropic,
  openai, httpx, twikit, pytest.
- Prefer **pure functions + thin I/O wrappers** (see `reports.py`, `embeddings.py`,
  `duplicates.py`) — makes the prompt/scoring logic trivially testable.
- No numpy — dot products over a few thousand 3072-dim vectors are fast enough.
- Tests: `python -m pytest tests/`. The prompt and scoring are pure functions, so
  most tests assert on their output without hitting the network/LLM.

See [`CLAUDE.md`](CLAUDE.md) for environment gotchas and the project-specific
do's and don'ts before making changes.
