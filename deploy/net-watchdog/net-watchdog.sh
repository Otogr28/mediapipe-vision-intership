#!/usr/bin/env bash
# HalLMediaPipe network watchdog — keeps the Jetson reachable over Tailscale.
#
# Runs as root on a systemd timer (default every 2 min, and once at boot).
# Each run it:
#   0. re-asserts WiFi power-save OFF — the Realtek rtl8822ce vendor driver
#      sleeps the radio when idle, which drops the Tailscale NAT/DERP mapping
#      and makes the node "disappear" (the real cause of the vanishing box).
#   1. checks INTERNET (a 204 captive-portal probe); this probe traffic ALSO
#      keeps the radio awake, so the watchdog doubles as a keepalive.
#   2. if internet is down, escalates: re-activate the WiFi connection, then
#      restart NetworkManager.
#   3. checks TAILSCALE is logged in + BackendState=Running and can reach a
#      peer; if not, `tailscale up`, then restart tailscaled as a last resort.
#
# Idempotent and cheap when everything is healthy (just the 204 probe). Logs
# a one-line status to the journal AND a size-capped file (the journal is
# volatile on this image, so the file is the only cross-reboot history).
#
# Env overrides (via the systemd unit): WD_WIFI_DEV, WD_TIMEOUT, WD_LOG,
# WD_LOG_MAXLINES.
set -uo pipefail   # NOT -e: a failing remediation step must not abort the run

WIFI_DEV="${WD_WIFI_DEV:-}"
NET_TIMEOUT="${WD_TIMEOUT:-6}"
LOG_FILE="${WD_LOG:-/var/log/hall-net-watchdog.log}"
LOG_MAXLINES="${WD_LOG_MAXLINES:-1000}"
PROBE_URLS=(
  "http://connectivitycheck.gstatic.com/generate_204"
  "http://cp.cloudflare.com/generate_204"
)

log() {
  # stdout -> journal (systemd captures it); also append to the capped file.
  local line="$(date '+%Y-%m-%d %H:%M:%S') $*"
  echo "$line"
  echo "$line" >> "$LOG_FILE" 2>/dev/null || true
}

cap_log() {
  # Keep only the last LOG_MAXLINES so the file never grows unbounded.
  [ -f "$LOG_FILE" ] || return 0
  local n; n="$(wc -l < "$LOG_FILE" 2>/dev/null || echo 0)"
  if [ "$n" -gt "$LOG_MAXLINES" ]; then
    tail -n "$LOG_MAXLINES" "$LOG_FILE" > "${LOG_FILE}.tmp" 2>/dev/null \
      && mv "${LOG_FILE}.tmp" "$LOG_FILE"
  fi
}

detect_wifi_dev() {
  [ -n "$WIFI_DEV" ] && { echo "$WIFI_DEV"; return; }
  local d
  d="$(nmcli -t -f DEVICE,TYPE dev 2>/dev/null \
        | awk -F: '$2=="wifi"{print $1; exit}')"
  echo "${d:-wlP1p1s0}"
}

active_wifi_conn() {
  nmcli -t -f NAME,TYPE,DEVICE connection show --active 2>/dev/null \
    | awk -F: -v d="$1" '$2=="802-11-wireless" && $3==d {print $1; exit}'
}

powersave_off() {
  local dev="$1"
  # The out-of-tree driver often ignores NetworkManager's property, so force
  # it directly too. Both are idempotent and silent when already off.
  iw dev "$dev" set power_save off 2>/dev/null || true
}

internet_up() {
  local url
  for url in "${PROBE_URLS[@]}"; do
    if curl -fsS -o /dev/null --max-time "$NET_TIMEOUT" "$url" 2>/dev/null; then
      return 0
    fi
  done
  # Last resort: an ICMP echo in case HTTP egress is filtered but IP is up.
  ping -c1 -W"$NET_TIMEOUT" 1.1.1.1 >/dev/null 2>&1
}

tailscale_healthy() {
  # BackendState must be Running; also require Self.Online=true so we catch
  # the "daemon up but control unreachable" case. Prefer jq (present on this
  # image); fall back to a grep parse if it is ever missing.
  local json state online
  json="$(tailscale status --json 2>/dev/null)" || return 1
  if command -v jq >/dev/null 2>&1; then
    state="$(printf '%s' "$json" | jq -r '.BackendState // empty' 2>/dev/null)"
    online="$(printf '%s' "$json" | jq -r '.Self.Online // false' 2>/dev/null)"
  else
    state="$(printf '%s' "$json" | grep -o '"BackendState":"[^"]*"' | head -1 | cut -d'"' -f4)"
    # Self is serialized before any Peer (verified), so the first Online flag
    # is Self's.
    online="$(printf '%s' "$json" | grep -o '"Online":[a-z]*' | head -1 | cut -d: -f2)"
  fi
  [ "$state" = "Running" ] && [ "$online" = "true" ]
}

main() {
  local dev conn healed=""
  dev="$(detect_wifi_dev)"

  # 0. Always re-assert power-save off (root-cause guard).
  powersave_off "$dev"

  # 1. Internet.
  if ! internet_up; then
    log "WARN internet DOWN on ${dev} — re-activating WiFi connection"
    healed="net"
    conn="$(active_wifi_conn "$dev")"
    if [ -n "$conn" ]; then
      nmcli connection up "$conn" >/dev/null 2>&1 || true
    else
      nmcli device connect "$dev" >/dev/null 2>&1 || true
    fi
    sleep 5
    powersave_off "$dev"
    if ! internet_up; then
      log "WARN internet still DOWN — restarting NetworkManager"
      systemctl restart NetworkManager 2>/dev/null || true
      sleep 8
      powersave_off "$dev"
    fi
    if internet_up; then
      log "OK internet recovered after WiFi remediation"
    else
      log "ERR internet STILL down after remediation"
    fi
  fi

  # 2. Tailscale (needs internet; try anyway — `up` is harmless offline).
  if ! tailscale_healthy; then
    log "WARN tailscale not healthy — running 'tailscale up'"
    healed="${healed:+$healed,}tailscale"
    timeout 30 tailscale up 2>/dev/null || true
    # `tailscale up` returns before Self.Online flips true (reconnecting to
    # DERP/control takes a second or two), so poll briefly before escalating
    # — otherwise every transient needlessly restarts the daemon.
    for _ in 1 2 3 4; do
      tailscale_healthy && break
      sleep 2
    done
    if ! tailscale_healthy; then
      log "WARN tailscale still down after 'up' — restarting tailscaled"
      systemctl restart tailscaled 2>/dev/null || true
      sleep 3
      timeout 30 tailscale up 2>/dev/null || true
    fi
    if tailscale_healthy; then
      log "OK tailscale recovered"
    else
      log "ERR tailscale STILL down after remediation"
    fi
  fi

  # Healthy runs stay quiet in the file (one heartbeat/hour) to avoid noise,
  # but always emit to the journal for `journalctl -u`.
  if [ -z "$healed" ]; then
    local min; min="$(date '+%M')"
    echo "$(date '+%Y-%m-%d %H:%M:%S') OK net+tailscale healthy (${dev})"
    if [ "$min" = "00" ]; then
      log "OK heartbeat — net+tailscale healthy (${dev})"
    fi
  fi

  cap_log
}

main "$@"
