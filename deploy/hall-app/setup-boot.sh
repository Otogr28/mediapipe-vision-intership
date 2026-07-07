#!/usr/bin/env bash
# One-time "appliance" setup — run ON the Jetson (directly or over ssh):
#
#   bash ~/HalLMediaPipe/deploy/hall-app/setup-boot.sh
#
# Turns the device into a boot-to-kiosk appliance that updates itself:
#   1. converts ~/HalLMediaPipe (old rsync copy) into a git checkout of
#      origin/main — untracked models/ and .trt_cache/ survive
#   2. repoints the hallrun/hallkiosk launchers into the checkout
#   3. installs user systemd units: hallkiosk.service (starts with the
#      graphical session) + hall-update.timer (polls origin/main every
#      minute and restarts the kiosk when a new commit lands)
#   4. disables screen blanking/locking for kiosk duty
#
# NOT done here (needs sudo — run once, see deploy/hall-app/README):
#   sudo loginctl enable-linger jetson
#   GDM autologin in /etc/gdm3/custom.conf ([daemon] AutomaticLoginEnable)
set -euo pipefail

APP_DIR="${HALL_APP_DIR:-$HOME/HalLMediaPipe}"
REPO_URL="${HALL_REPO_URL:-https://github.com/Otogr28/mediapipe-vision-intership.git}"

# systemctl --user / gsettings need the user bus when invoked over ssh.
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"

echo ">> [1/4] git checkout at $APP_DIR"
if [ ! -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" init -b main
  git -C "$APP_DIR" remote add origin "$REPO_URL"
  git -C "$APP_DIR" fetch --depth 1 origin main
  git -C "$APP_DIR" reset --hard origin/main
else
  git -C "$APP_DIR" fetch origin main
  git -C "$APP_DIR" reset --hard origin/main
fi
chmod +x "$APP_DIR/deploy/hall-app/hallrun" \
         "$APP_DIR/deploy/hall-app/hallkiosk" \
         "$APP_DIR/deploy/hall-app/hall-update.sh"

echo ">> [2/4] launchers"
mkdir -p "$HOME/.local/bin"
ln -sf "$APP_DIR/deploy/hall-app/hallrun" "$HOME/.local/bin/hallrun"
ln -sf "$APP_DIR/deploy/hall-app/hallkiosk" "$HOME/.local/bin/hallkiosk"
# rsync-era copies at the repo root would shadow the checkout — drop them.
rm -f "$APP_DIR/hallrun" "$APP_DIR/hallkiosk"

echo ">> [3/4] systemd user units"
mkdir -p "$HOME/.config/systemd/user"
cp "$APP_DIR"/deploy/hall-app/systemd/hallkiosk.service \
   "$APP_DIR"/deploy/hall-app/systemd/hall-update.service \
   "$APP_DIR"/deploy/hall-app/systemd/hall-update.timer \
   "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable hallkiosk.service hall-update.timer
systemctl --user restart hall-update.timer

echo ">> [4/4] kiosk display hygiene (no blanking / no lock)"
gsettings set org.gnome.desktop.session idle-delay 0 2>/dev/null || true
gsettings set org.gnome.desktop.screensaver lock-enabled false 2>/dev/null || true

echo ">> done. Remaining one-time sudo steps (see header): linger + autologin."
