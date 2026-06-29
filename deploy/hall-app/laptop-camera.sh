#!/usr/bin/env bash
# Expose THIS laptop's webcam as an MJPEG stream on the tailnet, so the Jetson
# can pull it as a remote camera source for inference.
#
# Reuses the repo's existing MJPEG server (../camera-stream/camera_stream.py),
# run through `uv` so the project's OpenCV is available. Ctrl-C to stop.
#
#   deploy/hall-app/laptop-camera.sh
#
# Override the webcam device / port with env vars:
#   CAM_DEVICE=2 CAM_PORT=8091 deploy/hall-app/laptop-camera.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

export CAM_DEVICE="${CAM_DEVICE:-0}"
export CAM_PORT="${CAM_PORT:-8091}"
export CAM_BIND="${CAM_BIND:-auto}"      # auto -> this laptop's Tailscale IP
export CAM_WIDTH="${CAM_WIDTH:-1280}"
export CAM_HEIGHT="${CAM_HEIGHT:-720}"
export CAM_FPS="${CAM_FPS:-30}"

exec uv run --project "$REPO_ROOT" python \
  "$REPO_ROOT/deploy/camera-stream/camera_stream.py"
