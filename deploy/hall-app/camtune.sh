#!/usr/bin/env bash
# Sweep one camera control against the LIVE exhibit and bring back one frame
# per value, so the backlight settings are chosen from pictures of the actual
# room instead of guessed.
#
#   deploy/hall-app/camtune.sh exposure 80 120 160 200 250
#   deploy/hall-app/camtune.sh gain 0 40 80 120 160
#   deploy/hall-app/camtune.sh brightness 96 128 160 192
#   deploy/hall-app/camtune.sh --show                 # print every control
#
# For the backlight at this exhibit, sweep `exposure` and `gain`: the picture
# has to be metered for the person and the windows allowed to blow out. The
# zoom/pan/tilt controls are reachable here too, but cropping the frame is
# ruled out by the operator — the visitor sees this feed behind every scene,
# so a tighter frame changes what the exhibit looks like.
#
# It does NOT stop the kiosk: UVC controls belong to the device, not to the
# process holding it, so the values can be changed from a second connection
# while the app keeps streaming — and the frame comes from the app's own
# /snapshot.jpg, which is exactly what the detector sees.
#
# Every control it touched is restored on exit, including on Ctrl-C, so a
# sweep can never be what leaves the exhibit mis-exposed. Once a value is
# chosen, make it permanent as HALL_CAM_<CONTROL> in `hallkiosk` — this script
# only ever tunes, it does not persist anything.
#
# Override the target with:  JETSON_HOST=jetson@<ip> deploy/hall-app/camtune.sh ...
set -euo pipefail

JETSON_HOST="${JETSON_HOST:-jetson@100.91.206.114}"
HEALTH_HOST="${HALL_HEALTH_HOST:-${JETSON_HOST#*@}}"
PORT="${HALL_STREAM_PORT:-8092}"
OUT_DIR="${CAMTUNE_OUT:-/tmp/camtune}"
# Frames to let the camera settle after a change: exposure and white balance
# ramp over several frames, so grabbing immediately shows the OLD picture.
SETTLE_S="${CAMTUNE_SETTLE_S:-1.5}"

# HALL_CAM_* key -> the v4l2 control name the camera actually publishes.
declare -A CTRL=(
  [power_line]=power_line_frequency
  [backlight]=backlight_compensation
  [brightness]=brightness
  [contrast]=contrast
  [saturation]=saturation
  [sharpness]=sharpness
  [gain]=gain
  [auto_exposure]=auto_exposure
  [exposure]=exposure_time_absolute
  [dynamic_fps]=exposure_dynamic_framerate
  [auto_wb]=white_balance_automatic
  [wb]=white_balance_temperature
  [autofocus]=focus_automatic_continuous
  [focus]=focus_absolute
  [zoom]=zoom_absolute
  [pan]=pan_absolute
  [tilt]=tilt_absolute
)

# The capture node is whichever /dev/video* actually publishes controls: a UVC
# camera also claims a metadata node, and its number moves between reboots
# (this is the same trap src/capture.py resolves for the app).
find_node() {
  ssh "$JETSON_HOST" '
    for d in /dev/video*; do
      if v4l2-ctl -d "$d" --list-ctrls 2>/dev/null | grep -q .; then
        echo "$d"; exit 0
      fi
    done
    exit 1'
}

usage() {
  sed -n '2,26p' "$0" | sed 's/^# \?//'
  echo
  echo "Controls: ${!CTRL[*]}"
  exit 1
}

[ $# -ge 1 ] || usage

NODE="$(find_node)" || { echo "camtune: no camera on $JETSON_HOST" >&2; exit 1; }
echo ">> camera node on the Jetson: $NODE"

if [ "$1" = "--show" ]; then
  ssh "$JETSON_HOST" "v4l2-ctl -d $NODE --list-ctrls"
  exit 0
fi

KEY="$1"; shift
NAME="${CTRL[$KEY]:-}"
[ -n "$NAME" ] || { echo "camtune: unknown control '$KEY'" >&2; usage; }
[ $# -ge 1 ] || { echo "camtune: give at least one value to try" >&2; usage; }

get_ctrl() { ssh "$JETSON_HOST" "v4l2-ctl -d $NODE --get-ctrl $1" | cut -d' ' -f2; }
set_ctrl() { ssh "$JETSON_HOST" "v4l2-ctl -d $NODE --set-ctrl $1=$2" >/dev/null; }

# Remember what to put back. Anything this script changes goes in here BEFORE
# it is changed, and the trap restores the lot however the script ends.
declare -A RESTORE=()
remember() { [ -n "${RESTORE[$1]+x}" ] || RESTORE[$1]="$(get_ctrl "$1")"; }
restore_all() {
  for c in "${!RESTORE[@]}"; do
    echo ">> restoring $c=${RESTORE[$c]}"
    set_ctrl "$c" "${RESTORE[$c]}" || true
  done
}
trap restore_all EXIT INT TERM

# An absolute control reads `flags=inactive` while its automatic counterpart
# owns it, so the mode has to be switched off first or every value is ignored.
case "$KEY" in
  exposure) remember auto_exposure; set_ctrl auto_exposure 1 ;;
  wb)      remember white_balance_automatic; set_ctrl white_balance_automatic 0 ;;
  focus)   remember focus_automatic_continuous; set_ctrl focus_automatic_continuous 0 ;;
esac
remember "$NAME"

mkdir -p "$OUT_DIR"
rm -f "$OUT_DIR/$KEY"-*.jpg

for v in "$@"; do
  set_ctrl "$NAME" "$v"
  got="$(get_ctrl "$NAME")"
  sleep "$SETTLE_S"
  f="$OUT_DIR/$KEY-$v.jpg"
  if curl -sf --max-time 10 -o "$f" "http://$HEALTH_HOST:$PORT/snapshot.jpg"; then
    printf '   %-12s asked %-8s got %-8s -> %s\n' "$NAME" "$v" "$got" "$f"
  else
    echo "   $NAME=$v: the backend did not answer on :$PORT (is the kiosk up?)" >&2
  fi
done

echo
echo ">> frames in $OUT_DIR"
echo ">> pick a value, then make it permanent in deploy/hall-app/hallkiosk:"
echo "     export HALL_CAM_${KEY^^}=\"\${HALL_CAM_${KEY^^}:-<value>}\""
