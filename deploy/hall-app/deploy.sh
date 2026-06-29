#!/usr/bin/env bash
# Deploy the HalLMediaPipe interactive app to the Jetson over Tailscale SSH.
# Run on the laptop, from anywhere:  deploy/hall-app/deploy.sh
#
# What it does:
#   1. rsyncs src/ + models/ (the .task files) to ~/HalLMediaPipe on the Jetson
#   2. installs the `hallrun` launcher into ~/.local/bin
#   3. installs the one missing Python dep (moderngl) into the user site —
#      mediapipe and opencv already ship in the Jetson's system Python, so we
#      reuse those instead of building them from source under uv.
#
# Nothing auto-starts. The app is interactive: run `hallrun` ON the Jetson
# (with a monitor + the C920 attached) to start it.
#
# Override the target with:  JETSON_HOST=jetson@<ip> deploy/hall-app/deploy.sh
set -euo pipefail

JETSON_HOST="${JETSON_HOST:-jetson@100.91.206.114}"
APP_DIR_REMOTE="${APP_DIR_REMOTE:-HalLMediaPipe}"   # relative to the remote $HOME
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SRC_DIR/../.." && pwd)"

echo ">> syncing code + models to ${JETSON_HOST}:~/${APP_DIR_REMOTE}"
rsync -az --delete \
  --exclude '.venv' --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' \
  --exclude '.vscode' --exclude 'deploy' \
  "$REPO_ROOT/src" "$REPO_ROOT/models" "$REPO_ROOT/pyproject.toml" "$REPO_ROOT/README.md" \
  "$JETSON_HOST:~/$APP_DIR_REMOTE/"

echo ">> installing launcher + deps on the Jetson"
scp "$SRC_DIR/hallrun" "$JETSON_HOST:~/$APP_DIR_REMOTE/hallrun"
ssh "$JETSON_HOST" "bash -s" <<REMOTE
set -euo pipefail
chmod +x "\$HOME/$APP_DIR_REMOTE/hallrun"
mkdir -p "\$HOME/.local/bin"
ln -sf "\$HOME/$APP_DIR_REMOTE/hallrun" "\$HOME/.local/bin/hallrun"
# moderngl (+ glcontext) is the only dep missing from the system Python; it has
# no aarch64 wheel so pip builds it from sdist (~30s, needs gcc — present).
python3 -c "import moderngl" 2>/dev/null && echo "   moderngl: already present" \
  || pip3 install --user moderngl
echo "   launcher: \$HOME/.local/bin/hallrun"
REMOTE

echo
echo ">> done. To run the app (on the Jetson, monitor + C920 attached):"
echo "     hallrun                                  # from the Jetson desktop terminal"
echo "   or push it onto the local monitor over SSH:"
echo "     ssh ${JETSON_HOST} 'DISPLAY=:0 ~/.local/bin/hallrun'"
