#!/usr/bin/env bash
# Auto-updater — runs ON the Jetson, fired by hall-update.timer (~60 s).
#
# Polls origin/main; when a new commit lands, hard-resets the checkout and
# restarts the kiosk service. This is the "push to main → the Jetson
# updates itself" loop: the laptop pushes (web/dist is COMMITTED, so no
# build step exists on the device) and within a minute the kiosk reloads.
#
# Untracked files (models/, .trt_cache/, logs) survive the reset — only
# tracked content moves. Requires ~/HalLMediaPipe to be a git checkout
# (deploy/hall-app/setup-boot.sh converts the old rsync copy).
set -euo pipefail

APP_DIR="${HALL_APP_DIR:-$HOME/HalLMediaPipe}"
PORT="${HALL_STREAM_PORT:-8092}"
cd "$APP_DIR"

# ---- self-healing watchdog (runs every timer tick, BEFORE the git check) --
# A wedged V4L2 camera reopen can freeze the whole backend process (a
# driver ioctl hangs holding the GIL): the service still reads "active"
# but the HTTP server stops answering. Two consecutive failed probes
# (~2 min) once the service is past its startup window (first-launch
# TensorRT engine builds take ~2 min) => restart the kiosk.
STRIKES_FILE="/tmp/hall-health.strikes"
if systemctl --user is-active --quiet hallkiosk.service 2>/dev/null; then
  # Arithmetic in SECONDS via bash only — mawk's %d truncates the µs
  # uptime to int32 and silently produced negative ages (inert watchdog).
  started_us="$(systemctl --user show -p ActiveEnterTimestampMonotonic --value hallkiosk.service 2>/dev/null || echo 0)"
  started_s=$(( ${started_us:-0} / 1000000 ))
  now_s="$(cut -d. -f1 /proc/uptime)"
  age_s=$(( now_s - started_s ))
  if [ "$started_s" -gt 0 ] && [ "$age_s" -gt 240 ]; then
    if curl -sf -m 3 "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
      rm -f "$STRIKES_FILE"
    else
      strikes=$(( $(cat "$STRIKES_FILE" 2>/dev/null || echo 0) + 1 ))
      echo "$strikes" > "$STRIKES_FILE"
      echo "hall-update: healthz strike $strikes/2 (service age ${age_s}s)"
      if [ "$strikes" -ge 2 ]; then
        rm -f "$STRIKES_FILE"
        echo "hall-update: kiosk unresponsive -> restarting"
        systemctl --user restart hallkiosk.service || true
      fi
    fi
  fi
fi

git fetch --quiet origin main
LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse origin/main)"
[ "$LOCAL" = "$REMOTE" ] && exit 0

echo "hall-update: ${LOCAL:0:10} -> ${REMOTE:0:10}"
git reset --hard --quiet origin/main
chmod +x deploy/hall-app/hallrun deploy/hall-app/hallkiosk \
  deploy/hall-app/hall-update.sh 2>/dev/null || true

# Refresh the systemd units too (setup-boot.sh COPIES them, so unit changes
# would otherwise never reach the device).
cp deploy/hall-app/systemd/hallkiosk.service \
   deploy/hall-app/systemd/hall-update.service \
   deploy/hall-app/systemd/hall-update.timer \
   "$HOME/.config/systemd/user/" 2>/dev/null || true
systemctl --user daemon-reload 2>/dev/null || true

# Restart the kiosk so the new backend + frontend go live. `|| true`: on a
# headless boot (no graphical session yet) the service simply isn't active.
systemctl --user restart hallkiosk.service 2>/dev/null || true
