#!/usr/bin/env bash
# Deploy the HalLMediaPipe interactive app to the Jetson over Tailscale SSH.
# Run on the laptop, from anywhere:  deploy/hall-app/deploy.sh
#
# What it does:
#   1. builds the web frontend (web/ -> web/dist, needs node on the laptop
#      only) when node_modules is present; skipped otherwise
#   2. rsyncs src/ + models/ (the .task files) + web/dist to ~/HalLMediaPipe
#   3. installs the `hallrun` + `hallkiosk` launchers into ~/.local/bin
#   4. installs the one missing Python dep (moderngl) into the user site —
#      mediapipe and opencv already ship in the Jetson's system Python, so we
#      reuse those instead of building them from source under uv.
#
# Nothing auto-starts. The app is interactive: run `hallrun` (cv2 window) or
# `hallkiosk` (browser UI fullscreen) ON the Jetson (monitor + webcam attached).
#
# Override the target with:  JETSON_HOST=jetson@<ip> deploy/hall-app/deploy.sh
set -euo pipefail

JETSON_HOST="${JETSON_HOST:-jetson@100.91.206.114}"
APP_DIR_REMOTE="${APP_DIR_REMOTE:-HalLMediaPipe}"   # relative to the remote $HOME
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SRC_DIR/../.." && pwd)"

if [ -d "$REPO_ROOT/web/node_modules" ]; then
  echo ">> building web frontend (web/ -> web/dist)"
  (cd "$REPO_ROOT/web" && npm run build)
elif [ ! -d "$REPO_ROOT/web/dist" ]; then
  echo ">> WARNING: web/dist missing and web/node_modules not installed —"
  echo "   skipping the frontend; hallkiosk will not work until you run"
  echo "   (cd web && npm install && npm run build) and redeploy."
fi

echo ">> syncing code + models to ${JETSON_HOST}:~/${APP_DIR_REMOTE}"
rsync -az --delete \
  --exclude '.venv' --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' \
  --exclude '.vscode' --exclude 'deploy' \
  "$REPO_ROOT/src" "$REPO_ROOT/models" "$REPO_ROOT/pyproject.toml" "$REPO_ROOT/README.md" \
  "$JETSON_HOST:~/$APP_DIR_REMOTE/"

if [ -d "$REPO_ROOT/web/dist" ]; then
  echo ">> syncing web frontend (dist only — node never runs on the Jetson)"
  ssh "$JETSON_HOST" "mkdir -p ~/$APP_DIR_REMOTE/web"
  rsync -az --delete "$REPO_ROOT/web/dist" "$JETSON_HOST:~/$APP_DIR_REMOTE/web/"
fi

echo ">> installing launchers + deps on the Jetson"
scp "$SRC_DIR/hallrun" "$JETSON_HOST:~/$APP_DIR_REMOTE/hallrun"
scp "$SRC_DIR/hallkiosk" "$JETSON_HOST:~/$APP_DIR_REMOTE/hallkiosk"
ssh "$JETSON_HOST" "bash -s" <<REMOTE
set -euo pipefail
chmod +x "\$HOME/$APP_DIR_REMOTE/hallrun" "\$HOME/$APP_DIR_REMOTE/hallkiosk"
mkdir -p "\$HOME/.local/bin"
ln -sf "\$HOME/$APP_DIR_REMOTE/hallrun" "\$HOME/.local/bin/hallrun"
ln -sf "\$HOME/$APP_DIR_REMOTE/hallkiosk" "\$HOME/.local/bin/hallkiosk"
# moderngl (+ glcontext) is the only dep missing from the system Python; it has
# no aarch64 wheel so pip builds it from sdist (~30s, needs gcc — present).
python3 -c "import moderngl" 2>/dev/null && echo "   moderngl: already present" \
  || pip3 install --user moderngl
echo "   launchers: \$HOME/.local/bin/hallrun, \$HOME/.local/bin/hallkiosk"
REMOTE

echo
echo ">> done. To run the app (on the Jetson, monitor + webcam attached):"
echo "     hallrun                                  # cv2 window (classic mode)"
echo "     hallkiosk                                # browser UI, fullscreen kiosk"
echo "   or push it onto the local monitor over SSH:"
echo "     ssh ${JETSON_HOST} 'DISPLAY=:0 ~/.local/bin/hallkiosk'"
