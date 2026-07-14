#!/usr/bin/env bash
# Deploy the network watchdog to the Jetson over Tailscale SSH.
# Run on the laptop, from anywhere:  deploy/net-watchdog/deploy.sh
#
# rsyncs this dir to the Jetson and runs install.sh under sudo there.
# Override the target with:  JETSON_HOST=yahboom deploy/net-watchdog/deploy.sh
set -euo pipefail

JETSON_HOST="${JETSON_HOST:-yahboom}"
REMOTE_DIR="${REMOTE_DIR:-hall-net-watchdog-src}"   # relative to remote $HOME
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ">> syncing watchdog sources to ${JETSON_HOST}:~/${REMOTE_DIR}"
rsync -az --delete \
  --exclude '.git' --exclude '*.log' \
  "$SRC_DIR/" "$JETSON_HOST:~/$REMOTE_DIR/"

echo ">> running installer on ${JETSON_HOST} (sudo)"
# -t for a tty so sudo can prompt if the passwordless rule isn't in place.
ssh -t "$JETSON_HOST" "cd ~/$REMOTE_DIR && sudo ./install.sh"
