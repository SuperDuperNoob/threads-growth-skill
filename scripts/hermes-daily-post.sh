#!/usr/bin/env bash
# Hermes daily auto-post — reference implementation of docs/hermes-orbit-runbook.md.
#
# Generates Threads drafts via Orbit, applies the >=75 score floor + topic-variety
# filter, schedules up to N to Threads+Facebook, and logs every run. Fails SAFE:
# any error path posts nothing and exits without scheduling.
#
# Hermes may run this verbatim, or use it as the spec for its own agentic version
# (where the "decide" step uses Hermes' judgment instead of jq). Requires: jq.
#
# Usage (cron, 07:00 HKT):  hermes-daily-post.sh
# Env:  ORBIT_HOME (required), MIN_SCORE (default 75), MAX_POSTS (default 3)
set -euo pipefail

MIN_SCORE="${MIN_SCORE:-75}"
MAX_POSTS="${MAX_POSTS:-3}"
LOG="${ORBIT_HOME:-$HOME/.orbit}/hermes.log"
TODAY="$(date +%Y-%m-%d)"

log() { echo "$TODAY | $*" >> "$LOG"; }

# 1. Pre-flight -------------------------------------------------------------
[ -n "${ORBIT_HOME:-}" ] && [ -d "$ORBIT_HOME" ] || { echo "ORBIT_HOME not mounted"; log "ABORT: ORBIT_HOME not mounted"; exit 1; }
command -v orbit >/dev/null || { echo "orbit not on PATH"; log "ABORT: orbit missing"; exit 1; }
command -v jq    >/dev/null || { echo "jq required"; log "ABORT: jq missing"; exit 1; }

# 2. Generate ---------------------------------------------------------------
CAND="$(mktemp)"
if ! orbit draft --json > "$CAND" 2>>"$LOG"; then
  log "SKIP: generation failed (see stderr above)"
  rm -f "$CAND"; exit 0
fi

# 3. Decide -----------------------------------------------------------------
# Drop < MIN_SCORE; drop topics overlapping recent_topics; take top MAX_POSTS by
# score. (Hermes' own version can reason more richly than this jq filter.)
PICKS="$(jq -r --argjson floor "$MIN_SCORE" --argjson n "$MAX_POSTS" '
  .recent_topics as $recent
  | [ .candidates[]
      | select(.score >= $floor)
      # drop if this candidate.topic contains any recent topic substring (case-insensitive)
      | . as $c
      | select( ( $recent
                  | map(ascii_downcase)
                  | map(select(. != ""))
                  | any(. as $r | ($c.topic | ascii_downcase | contains($r))) ) | not ) ]
  | sort_by(-.score) | .[:$n] | .[].draft_id
' "$CAND" 2>/dev/null || true)"

SEEN="$(jq -r '[.candidates[].score] | join(",")' "$CAND")"
if [ -z "$PICKS" ]; then
  log "SKIP: no candidate >= $MIN_SCORE (scores: $SEEN)"
  rm -f "$CAND"; exit 0
fi

# 4. Schedule ---------------------------------------------------------------
OK=()
for id in $PICKS; do
  if orbit drafts schedule "$id" >/tmp/sched.json 2>>"$LOG"; then
    OK+=("$id")
  else
    log "WARN: schedule of draft $id failed (left local; see stderr)"
  fi
done

# 5. Report -----------------------------------------------------------------
log "seen: $SEEN | picked: $(echo $PICKS | tr ' ' ',') | scheduled: ${OK[*]:-none}"
rm -f "$CAND"
