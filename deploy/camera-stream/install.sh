#!/usr/bin/env bash
# Install the HalLMediaPipe camera stream service on the Jetson.
# Run ON the Jetson (needs root):  sudo ./install.sh
#
# Privacy-first: this installs everything but leaves the stream OFF and
# disabled-on-boot. The camera does nothing until someone runs `camctl on`.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo: sudo $0" >&2
  exit 1
fi

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR=/opt/hall-camera
SERVICE_USER="${SERVICE_USER:-jetson}"

echo ">> installing app files to ${APP_DIR}"
install -d "$APP_DIR"
install -m 0755 "$SRC_DIR/camera_stream.py" "$APP_DIR/camera_stream.py"
install -m 0755 "$SRC_DIR/camctl"           "$APP_DIR/camctl"
ln -sf "$APP_DIR/camctl" /usr/local/bin/camctl

echo ">> installing systemd unit"
install -m 0644 "$SRC_DIR/camera-stream.service" /etc/systemd/system/camera-stream.service

echo ">> installing scoped passwordless sudoers rule for '${SERVICE_USER}'"
tmp_sudo="$(mktemp)"
sed "s/__USER__/${SERVICE_USER}/g" "$SRC_DIR/camera-stream.sudoers" > "$tmp_sudo"
if visudo -cf "$tmp_sudo" >/dev/null; then
  install -m 0440 "$tmp_sudo" /etc/sudoers.d/camera-stream
  rm -f "$tmp_sudo"
else
  rm -f "$tmp_sudo"
  echo "ERROR: generated sudoers file failed validation; aborting." >&2
  exit 1
fi

systemctl daemon-reload

cat <<EOF

Installed. The stream is OFF by default (lab privacy) and will NOT start on boot.

  Turn ON  :  camctl on      (laptop:  ssh ${SERVICE_USER}@<tailscale-ip> camctl on)
  Turn OFF :  camctl off
  Status   :  camctl status

EOF
camctl status || true
