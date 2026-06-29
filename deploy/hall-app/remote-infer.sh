#!/usr/bin/env bash
# Remote inference:
#   laptop webcam  --MJPEG-->  Jetson (MediaPipe + render)  --MJPEG-->  browser
#
#   deploy/hall-app/remote-infer.sh           # start everything + open the viewer
#   deploy/hall-app/remote-infer.sh stop      # stop the laptop camera + Jetson app
#
# Both halves run DETACHED (the laptop camera server and the Jetson app), so a
# dropped SSH connection, a closed terminal, or the browser opening can NOT
# take down the inference. Stopping is explicit (the `stop` subcommand). No
# monitor needed on the Jetson.
#
# Assumes the app is already deployed (run deploy/hall-app/deploy.sh once).
set -euo pipefail

JETSON_HOST="${JETSON_HOST:-jetson@100.91.206.114}"
JETSON_TS_IP="${JETSON_TS_IP:-${JETSON_HOST#*@}}"   # IP the browser hits
CAM_PORT="${CAM_PORT:-8091}"                        # laptop camera server
OUT_PORT="${OUT_PORT:-8092}"                        # Jetson annotated-output server
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CAM_PID_FILE="${TMPDIR:-/tmp}/hall-laptop-cam.pid"

stop() {
  echo ">> stopping laptop camera + Jetson app..."
  if [ -f "$CAM_PID_FILE" ]; then
    kill "$(cat "$CAM_PID_FILE")" 2>/dev/null || true
    rm -f "$CAM_PID_FILE"
  fi
  pkill -f "deploy/camera-stream/camera_stream.py" 2>/dev/null || true
  ssh "$JETSON_HOST" 'pkill -f "src/main.py" 2>/dev/null || true' || true
  echo ">> stopped. (laptop webcam released)"
}

if [ "${1:-start}" = "stop" ]; then
  stop
  exit 0
fi

LAPTOP_TS_IP="$(tailscale ip -4 2>/dev/null | head -1 || true)"
if [ -z "$LAPTOP_TS_IP" ]; then
  echo "ERROR: can't find this laptop's Tailscale IP (is tailscaled up?)." >&2
  exit 1
fi

# Fresh start: clear any previous run so ports are free.
stop >/dev/null 2>&1 || true
sleep 1

echo ">> starting laptop camera server on http://${LAPTOP_TS_IP}:${CAM_PORT}/ (detached)"
CAM_PORT="$CAM_PORT" setsid "$SRC_DIR/laptop-camera.sh" >"${TMPDIR:-/tmp}/hall-laptop-cam.log" 2>&1 < /dev/null &
echo $! > "$CAM_PID_FILE"

# Wait for the laptop camera to actually serve before pointing the Jetson at it.
for i in $(seq 1 15); do
  sleep 1
  if curl -fsS -m 2 "http://${LAPTOP_TS_IP}:${CAM_PORT}/healthz" >/dev/null 2>&1; then
    echo "   laptop camera up"; break
  fi
  if [ "$i" = 15 ]; then
    echo "ERROR: laptop camera did not come up; see ${TMPDIR:-/tmp}/hall-laptop-cam.log" >&2
    stop; exit 1
  fi
done

echo ">> launching the app on the Jetson (headless, DETACHED) — logs to /tmp/hall-app.log on the device"
ssh "$JETSON_HOST" \
  "nohup env HALL_OUTPUT=stream \
   HALL_CAMERA='http://${LAPTOP_TS_IP}:${CAM_PORT}/stream.mjpg' \
   HALL_STREAM_BIND=auto \
   HALL_STREAM_PORT=${OUT_PORT} \
   ~/.local/bin/hallrun >/dev/null 2>&1 < /dev/null & sleep 1; echo '   jetson app launched'"

WATCH_URL="http://${JETSON_TS_IP}:${OUT_PORT}/"
echo ">> waiting for the Jetson output stream..."
up=""
for i in $(seq 1 25); do
  sleep 1
  if curl -fsS -m 2 "http://${JETSON_TS_IP}:${OUT_PORT}/healthz" >/dev/null 2>&1; then up=1; break; fi
done

if [ -n "$up" ]; then
  echo ">> LIVE. Watch it here:  ${WATCH_URL}"
  xdg-open "$WATCH_URL" >/dev/null 2>&1 || true
else
  echo ">> the output server is taking a while; open it manually:  ${WATCH_URL}"
fi

cat <<EOF

   Both halves run detached — nothing here will kill them.
   To stop:     $0 stop
   Jetson log:  ssh ${JETSON_HOST} 'tail -f /tmp/hall-app.log'
EOF
