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
cd "$APP_DIR"

git fetch --quiet origin main
LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse origin/main)"
[ "$LOCAL" = "$REMOTE" ] && exit 0

echo "hall-update: ${LOCAL:0:10} -> ${REMOTE:0:10}"
git reset --hard --quiet origin/main
chmod +x deploy/hall-app/hallrun deploy/hall-app/hallkiosk \
  deploy/hall-app/hall-update.sh 2>/dev/null || true

# Restart the kiosk so the new backend + frontend go live. `|| true`: on a
# headless boot (no graphical session yet) the service simply isn't active.
systemctl --user restart hallkiosk.service 2>/dev/null || true
