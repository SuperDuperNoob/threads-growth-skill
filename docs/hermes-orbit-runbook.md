# Hermes ↔ Orbit daily posting runbook

**Audience:** the Hermes agent (and Keith, for setup). This is the operating
manual Hermes follows to autonomously post to Threads + Facebook while Keith is
away. Hermes is the *decider* — Orbit only provides primitives.

## What Hermes does each day

Run this once per day (suggested 07:00 HKT, before the first posting slot):

### 1. Pre-flight (abort the whole run if any fail — post NOTHING)

```bash
test -d "$ORBIT_HOME" || { echo "ORBIT_HOME not mounted"; exit 1; }
orbit --version >/dev/null   || { echo "orbit not runnable"; exit 1; }
```

`$ORBIT_HOME` must point at the shared NAS Orbit dir (same one Keith's Mac uses).
If the NAS isn't mounted, STOP — never fall back to a stale local copy.

### 2. Generate candidates (no scheduling, JSON on stdout)

```bash
orbit draft --json > /tmp/orbit-candidates.json 2> /tmp/orbit-gen.log
```

- Exit non-zero → generation failed (bad auth, no bookmarks, OpenAI down).
  Log `/tmp/orbit-gen.log`, post nothing today, try again tomorrow.
- Stdout is **pure JSON**. Status/errors are on stderr.

JSON shape:
```json
{
  "generated_at": "2026-06-18T23:00:00Z",
  "recent_topics": ["omnigent", "pool", "codex-reset"],
  "candidates": [
    {"draft_id": 1101, "score": 88, "label": "high",
     "topic": "...", "text": "...", "signals": ["+ strong hook", "+ concrete number"]}
  ]
}
```

### 3. Decide (Hermes' judgment)

Apply, in order:
1. **Drop `score < 75`.** This is the quality floor. A sub-75 draft is worse
   than silence — Keith is recovering from a slump; weak posts hurt.
2. **Drop topic overlap.** If a candidate's `topic` covers the same
   brand/story as anything in `recent_topics`, drop it. The algorithm
   suppresses consecutive same-topic posts.
3. **Pick up to 3**, preferring the highest scores AND the most distinct topics
   from each other. Fewer is fine — **do not force 3.** Quality over cadence.
4. **If nothing clears the bar → skip the day.** Log why. This is a valid,
   expected outcome, not a failure.

### 4. Schedule each pick (the only step that posts to live accounts)

For each chosen `draft_id`:
```bash
orbit drafts schedule <draft_id> > /tmp/orbit-sched.json 2>> /tmp/orbit-gen.log
```
- Default slot = next free 9am/4pm/9pm HKT. Pass `--slot <UTC-ISO>` to pin.
- Exit 0 = scheduled to Threads + Facebook via Postiz. Exit non-zero = failed
  (e.g. Postiz auth expired); the draft stays saved locally for Keith to retry.
  **Do not retry-storm** — log it and move to the next pick.

### 5. Report

Append one line per run to `$ORBIT_HOME/hermes.log`:
```
2026-06-18 | seen: 6 (scores 88,85,83,61,40,22) | picked: 1101,1099 | skipped: rest <75 | scheduled OK
```

## The floor lives here, not in code

The `75` threshold is intentionally in this runbook, not hardcoded in Orbit, so
Keith can adjust it by editing this file (no redeploy) and Hermes can reason
around it — e.g. "two cleared 75 but both are OpenAI; post one, hold the other."

## Failure modes — all degrade to "post nothing"

| Failure | What Hermes does |
|---|---|
| NAS unmounted | pre-flight abort, log |
| `orbit draft --json` non-zero | log stderr, skip day |
| 0 candidates / all < 75 | skip day (expected), log reason |
| `orbit drafts schedule` non-zero | log, leave draft local, try next pick |

## Concurrency note (shared NAS)

Orbit guards DB writes with a `flock` on `$ORBIT_HOME/.writer.lock`. Still, avoid
running Hermes' daily job at the same time Keith's Mac runs `orbit sync`. The
07:00 HKT schedule is chosen to sit before Keith's usual morning sync.

## Setup checklist (Keith, before June 18)

- [ ] `~/.orbit/` moved to NAS; `ORBIT_HOME` set on Mac (verify Mac Orbit works)
- [ ] Hermes container mounts the same NAS path; `ORBIT_HOME` set there
- [ ] Smoke test: ask Hermes to run `orbit --version` and report output
- [ ] Supervised dry run: Hermes does steps 1–4 once while Keith watches
- [ ] Safety-net: 2–3 posts pre-scheduled for the first days of the trip
- [ ] Daily trigger enabled (cron or Hermes' own scheduler)
