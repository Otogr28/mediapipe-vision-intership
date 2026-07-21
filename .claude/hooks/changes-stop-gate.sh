#!/usr/bin/env bash
# Stop hook for HalLMediaPipe — strict logging gate for this repo's changes.md.
#
# If this session touched a HalLMediaPipe file (flag raised by
# changes-reminder.sh) and changes.md was NOT updated afterwards, block the turn
# from ending and tell the agent to log it first. Editing changes.md clears the
# flag. Loop-safe: only blocks once (honors stop_hook_active), so a genuinely
# unloggable change cannot trap the session.
set -euo pipefail

payload=$(cat)
active=$(printf '%s' "$payload" | jq -r '.stop_hook_active // false')
sid=$(printf '%s' "$payload" | jq -r '.session_id // "nosession"')
marker="${TMPDIR:-/tmp}/hall-changes-pending.$sid"

# Already nudged once this stop-cycle -> don't block again (prevents any loop).
[ "$active" = "true" ] && exit 0

# Nothing pending -> nothing to enforce.
[ -f "$marker" ] || exit 0

reason="You changed HalLMediaPipe files this session but have not logged it in \
HalLMediaPipe/changes.md yet. Before stopping, add ONE entry at the TOP of the «Entries» section \
following the anti-overwrite rule (never edit or delete existing entries, only add your own; run \
date \"+%Y-%m-%d %H:%M %Z\"  for the heading; fill Area · Status · Artifact · [Problem] · Changes · \
Tests to run, using this repo's status vocabulary). Editing changes.md clears this gate. If a change \
truly does not warrant a log entry, say so briefly and stop again. (SHARED.md is the agent \
coordination file — update it too after meaningful work, but it does not clear this gate.)"

jq -cn --arg r "$reason" '{decision:"block",reason:$r}'
