#!/usr/bin/env bash
# PostToolUse (Write|Edit) hook for HalLMediaPipe.
#
# Fires when a file of this repo is written or edited (src/, web/src/, deploy/,
# documentation/, tests/, configs, ...) and reminds the agent to append (never
# overwrite) an entry to this repo's changes.md. It raises a per-session
# "unlogged changes" flag that the Stop gate (changes-stop-gate.sh) enforces;
# editing changes.md clears the flag. Reads the hook JSON payload on stdin;
# emits additionalContext JSON on stdout (non-blocking).
#
# Adapted from the vault-root hook (.claude/hooks/ in Intership2026): same
# mechanism, but scoped to files INSIDE HalLMediaPipe/ and with this repo's
# exclusions — build output (web/dist), gitignored artifacts (models/,
# .trt_cache/), env/vcs dirs, and SHARED.md (the coordination log is where you
# log, not a change to log).
set -euo pipefail

payload=$(cat)
f=$(printf '%s' "$payload" | jq -r '.tool_input.file_path // empty')
sid=$(printf '%s' "$payload" | jq -r '.session_id // "nosession"')
marker="${TMPDIR:-/tmp}/hall-changes-pending.$sid"

[ -z "$f" ] && exit 0

# Only files inside THIS repo count (the vault root has its own log + hook).
case "$f" in
  */HalLMediaPipe/*) : ;;
  *) exit 0 ;;
esac

# Editing this repo's log itself clears the pending flag (the entry was added).
case "$f" in
  */HalLMediaPipe/changes.md) rm -f "$marker" 2>/dev/null || true; exit 0 ;;
esac

# Excluded: coordination log / build output / gitignored artifacts / vcs / envs.
case "$f" in
  */HalLMediaPipe/SHARED.md|*/web/dist/*|*/web/node_modules/*|*/models/*|*/.trt_cache/*|*/.git/*|*/.claude/*|*/.venv/*|*/__pycache__/*|*/node_modules/*)
    exit 0 ;;
esac

# Everything else in the repo counts. Flag it, then nudge the agent.
: > "$marker" 2>/dev/null || true

msg="You changed a HalLMediaPipe file ($f). When you finish THIS batch of work \
—or if a decision was made or a problem appeared/was resolved— add ONE entry at the TOP of the \
«Entries» section of HalLMediaPipe/changes.md. ANTI-OVERWRITE RULE: never edit or delete existing \
entries, ONLY add your own. Run  date \"+%Y-%m-%d %H:%M %Z\"  for the heading and follow the file's \
template (Area · Status · Artifact · [Problem] · Changes · Tests to run). One entry per batch, not \
one per file. Use this repo's status vocabulary (VERIFIED HEADLESS (mock) · SMOKE OK · DIST \
REBUILT/NOT REBUILT · PUSHED/NOT PUSHED · VERIFIED ON JETSON · PENDING JETSON TEST) and remember: \
web/src changes need npm run build + committed web/dist; state-contract changes need BOTH \
src/web/state.py and web/src/state/types.ts. This log complements SHARED.md (coordination), it does \
not replace it."

jq -cn --arg m "$msg" \
  '{hookSpecificOutput:{hookEventName:"PostToolUse",additionalContext:$m}}'
