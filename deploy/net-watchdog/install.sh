#!/usr/bin/env bash
# Install the HalLMediaPipe network watchdog on the Jetson.
# Run ON the Jetson (needs root):  sudo ./install.sh
#
# Installs three layers that together keep the box reachable over Tailscale:
#   1. WiFi power-save is disabled permanently — set on every known WiFi
#      connection (NM property) AND re-asserted on every link-up by a NM
#      dispatcher hook (the vendor driver ignores the NM property alone).
#   2. A watchdog script + systemd timer that every 2 min probes internet +
#      Tailscale and heals whatever is down (and whose probe traffic keeps
#      the radio awake).
#
# Idempotent: safe to re-run to update the scripts.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo: sudo $0" >&2
  exit 1
fi

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR=/opt/hall-net-watchdog

echo ">> installing watchdog script to ${APP_DIR}"
install -d "$APP_DIR"
install -m 0755 "$SRC_DIR/net-watchdog.sh" "$APP_DIR/net-watchdog.sh"

echo ">> installing systemd unit + timer"
install -m 0644 "$SRC_DIR/systemd/hall-net-watchdog.service" \
        /etc/systemd/system/hall-net-watchdog.service
install -m 0644 "$SRC_DIR/systemd/hall-net-watchdog.timer" \
        /etc/systemd/system/hall-net-watchdog.timer

echo ">> installing NetworkManager power-save dispatcher hook"
install -d /etc/NetworkManager/dispatcher.d
install -m 0755 "$SRC_DIR/dispatcher/99-hall-wifi-powersave-off" \
        /etc/NetworkManager/dispatcher.d/99-hall-wifi-powersave-off

echo ">> disabling WiFi power-save on all saved WiFi connections (NM property)"
# 2 = disable (0/1 = default/ignore -> often ends up ON with this driver).
while IFS=: read -r name type; do
  [ "$type" = "802-11-wireless" ] || continue
  nmcli connection modify "$name" 802-11-wireless.powersave 2 2>/dev/null \
    && echo "   set powersave=disable on '$name'" \
    || echo "   (could not modify '$name' — skipped)"
done < <(nmcli -t -f NAME,TYPE connection show)

echo ">> forcing power-save off on active WiFi device now"
for dev in $(nmcli -t -f DEVICE,TYPE dev 2>/dev/null \
             | awk -F: '$2=="wifi"{print $1}'); do
  iw dev "$dev" set power_save off 2>/dev/null \
    && echo "   $dev -> $(iw dev "$dev" get power_save 2>/dev/null)" || true
done

echo ">> enabling + starting the watchdog timer"
systemctl daemon-reload
systemctl enable --now hall-net-watchdog.timer

echo ">> running one watchdog pass now"
systemctl start hall-net-watchdog.service || true

cat <<EOF

Installed. The watchdog runs every 2 min (and 30 s after boot).

  Status    :  systemctl status hall-net-watchdog.timer
  Live logs :  journalctl -u hall-net-watchdog.service -f
  History   :  tail -f /var/log/hall-net-watchdog.log   (survives reboots)
  Run now   :  systemctl start hall-net-watchdog.service

WiFi power-save is now OFF (root cause of the vanishing-from-Tailscale drops).
EOF

echo ">> current watchdog log:"
tail -n 5 /var/log/hall-net-watchdog.log 2>/dev/null || true
