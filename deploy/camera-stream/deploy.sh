#!/usr/bin/env bash
# Deploy/update the camera stream service to the Jetson over Tailscale SSH.
# Run on the laptop:  ./deploy.sh
# You'll be asked for the Jetson sudo password once (for the install step).
#
# Override the target with:  JETSON_HOST=jetson@<ip> ./deploy.sh
set -euo pipefail

JETSON_HOST="${JETSON_HOST:-jetson@100.91.206.114}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REMOTE_TMP=/tmp/hall-camera-deploy

echo ">> copying files to ${JETSON_HOST}"
ssh "$JETSON_HOST" "mkdir -p '$REMOTE_TMP'"
scp "$SRC_DIR/camera_stream.py" \
    "$SRC_DIR/camera-stream.service" \
    "$SRC_DIR/camera-stream.sudoers" \
    "$SRC_DIR/camctl" \
    "$SRC_DIR/install.sh" \
    "$JETSON_HOST:$REMOTE_TMP/"

echo ">> installing on the Jetson (sudo password needed)"
ssh -t "$JETSON_HOST" "cd '$REMOTE_TMP' && sudo bash install.sh"

echo
echo ">> done. The stream is installed but OFF (privacy)."
echo "   Turn it on:  ssh ${JETSON_HOST} camctl on"
echo "   Then watch:  http://${JETSON_HOST#*@}:8090/"
