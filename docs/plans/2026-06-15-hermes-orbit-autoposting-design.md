# Hermes auto-posting via Orbit — design

**Date:** 2026-06-15
**Deadline:** 2026-06-18 (Keith leaves for holiday)
**Goal:** Hermes (an AI agent on Keith's Beelink) autonomously generates and
schedules Threads + Facebook posts daily via Orbit while Keith is away, with no
human in the loop and a quality floor so weak posts are skipped, not shipped.

## Decisions (locked with Keith)

- **Autonomy:** fully auto — Hermes drafts + schedules daily, no remote approval.
- **Trigger:** daily, fired inside Hermes' container (cron or Hermes' own loop).
- **Hermes is the *decider*** (world B): Orbit exposes primitives; Hermes' own
  reasoning is the orchestrator and quality gate.
- **Quality floor:** score ≥ 75/100; skip the day if nothing clears it.
- **Data location:** `~/.orbit/` moves to the shared NAS (UGreen/Synology);
  both Mac and Beelink point `ORBIT_HOME` there. Single source of truth.
- **Interface:** CLI commands with JSON stdout + meaningful exit codes — the
  universal lowest-common-denominator any agent runtime can drive.

## Architecture

Two-step split — **generate (Orbit) → decide (Hermes) → schedule (Orbit)**:

1. `orbit draft --json` — generate candidates, score each, print JSON, schedule
   nothing. Safe to run anytime.
2. `orbit drafts schedule <id>` — the ONLY command that touches live accounts.
   Wraps existing `do_handoff(draft_id)` → Threads + Facebook.

Rationale: Hermes can see scores + recent topics as data and reason over them
(layered nuance a hardcoded `if score < 75` can't do). Fails safe — any upstream
problem means `schedule` simply never runs. Clean blast-radius separation: one
auditable write-to-the-world command.

## Section 1 — Data & secrets (NAS)

- `ORBIT_HOME` env support: `db.py` and `config.py` change from
  `Path.home() / ".orbit"` to `Path(os.environ.get("ORBIT_HOME", ...))`.
- Move `~/.orbit/` → NAS; symlink on Mac, same mount in Hermes' container.
- **Single-writer lock:** `flock` on `$ORBIT_HOME/.writer.lock` around DB-writing
  commands → prevents SQLite-over-network corruption from concurrent Mac+Hermes.
- NAS unreachable at run time → fail loud, post nothing (never fall back to a
  stale local DB).

## Section 2 — Non-interactive commands

`orbit draft --json [--limit N]`:
- Reuses existing generation (bookmark ranking, embedding similarity, Sonnet,
  topic-fatigue + audience-width guards).
- Skips `_select_loop`, LinkedIn prompt, post-save prompt entirely.
- Scores each candidate via existing `_score_threads_draft_virality()`.
- Saves candidates as `status='draft'` rows (stable IDs), prints JSON:
  `{generated_at, recent_topics, candidates:[{draft_id,score,label,topic,text,signals}]}`.

`orbit drafts schedule <draft_id> [--slot ISO]`:
- Wraps `do_handoff(draft_id)` → Threads + Facebook.
- Default slot = next free 9am/4pm/9pm HKT via `next_slots()`.
- Prints `{ok, draft_id, slot, postIds}`; exit 0 success / non-zero failure.

## Section 3 — Daily procedure (Hermes runbook, repo-committed)

`docs/hermes-orbit-runbook.md` — logic in Hermes' reasoning, not Python:
1. Pre-flight: `$ORBIT_HOME` mounted + `orbit --version` works, else abort.
2. `orbit draft --json`, read candidates.
3. Decide: drop score < 75; drop topics overlapping `recent_topics`; pick up to
   3 most-distinct; if none qualify → skip day, log reason.
4. `orbit drafts schedule <id>` per pick; check exit code, no retry-storm.
5. Append to `$ORBIT_HOME/hermes.log`: candidates+scores, picks, slots, failures.

Floor lives in prose (not code) so it's adjustable without redeploy and Hermes
can reason around it. "Up to 3" is a ceiling, not a quota — quality over cadence.

## Section 4 — Failure modes (all fail to "post nothing")

| Failure | Behavior |
|---|---|
| NAS unmounted | pre-flight aborts, logged |
| DB lock held by Mac | flock waits, then skips day |
| AI key dead | `--json` non-zero, no schedule fires |
| Postiz auth expired | `schedule` non-zero, draft stays local, logged |
| All candidates < 75 | skip by design, logged |
| Bookmarks empty/stale | 0 candidates → skip day |

Safety net: pre-schedule 2–3 strong (≥75) posts before 6/18 so day-1 silence is
impossible even if Hermes' first run fails.

YAGNI (deliberately NOT building): push notifications, remote approval, web
dashboard, auto-retry queues. `hermes.log` is the audit trail on return.

## Section 5 — Build sequence

Day 1 (code, feature branch, TDD): ORBIT_HOME; flock lock; `draft --json`;
`drafts schedule`; full suite green; commit.
Day 2 (infra): NAS migration + Mac re-point + verify; write runbook; dry run
end-to-end on Mac.
Day 3 (Hermes, needs Beelink — Keith + Hermes): smoke test `orbit --version`;
one supervised dry run; pre-schedule safety-net posts; enable daily trigger.

Rollback: code on branch; NAS move is `mv`+symlink (reversible); trigger off
until final step. If step-10 dry run smells wrong → ship only safety-net posts,
shelve automation. Keith still covered for the trip.

## Boundary: what Claude does vs. Keith+Hermes

- Claude (this machine): all code + tests (Day 1), NAS move + Mac dry run (Day 2).
- Keith + Hermes (Beelink, physical/agent access Claude lacks): smoke test,
  supervised dry run, enable trigger (Day 3).
