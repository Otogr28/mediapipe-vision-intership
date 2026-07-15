#!/usr/bin/env bash
# Lock the Jetson desktop down for exhibit duty: NOTHING may pop up over the
# HalLMediaPipe kiosk, and the kiosk window stays above everything else.
#
# Run ON the Jetson (needs sudo for the system bits):
#     sudo deploy/hall-app/kiosk-lockdown.sh
# or from the laptop:
#     deploy/hall-app/deploy.sh          # ships it, then run the line above
#
# Idempotent — safe to re-run after an OS update re-enables something.
#
# What pops up on an untouched Ubuntu 22.04 / GNOME 42 desktop, and what this
# does about each (all of these were live on this board):
#   * GNOME notification banners  -> show-banners false (the global lever;
#     the per-plugin `active` keys were REMOVED in GNOME 42, so disabling
#     gsd-housekeeping/print-notifications individually is not possible)
#   * apport crash dialogs        -> /etc/default/apport enabled=0 + service off
#   * update-notifier apt nags    -> no-show-notifications true + autostart off
#   * gnome-software update nags  -> download-updates false + autostart off
#   * screen dimming / blanking   -> idle-dim false, idle-delay 0, no lock
#   * Firefox permission/update/
#     download prompts            -> /etc/firefox/policies/policies.json
#
# The always-on-top half lives in `hallkiosk` (it owns the browser lifecycle);
# this script only installs the tool it needs (wmctrl).
set -uo pipefail   # NOT -e: one unavailable schema must not abort the rest

KIOSK_USER="${KIOSK_USER:-jetson}"
UID_N="$(id -u "$KIOSK_USER")"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo: sudo $0" >&2
  exit 1
fi

# gsettings must talk to the USER's session bus, not root's.
gset() {
  local schema="$1" key="$2" val="$3"
  if sudo -u "$KIOSK_USER" \
       DISPLAY=:0 DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${UID_N}/bus" \
       gsettings set "$schema" "$key" "$val" 2>/dev/null; then
    echo "   $schema $key = $val"
  else
    echo "   (skipped: $schema $key — schema not present)"
  fi
}

echo ">> silencing GNOME notifications + idle behaviour for '${KIOSK_USER}'"
gset org.gnome.desktop.notifications show-banners false
gset org.gnome.desktop.notifications show-in-lock-screen false
gset com.ubuntu.update-notifier no-show-notifications true
# The board has no battery, but gsd-power still DIMS the screen on idle —
# on a kiosk that reads as the exhibit breaking.
gset org.gnome.settings-daemon.plugins.power idle-dim false
gset org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type nothing
gset org.gnome.desktop.session idle-delay 0
gset org.gnome.desktop.screensaver lock-enabled false
gset org.gnome.desktop.screensaver idle-activation-enabled false
gset org.gnome.software download-updates false
gset org.gnome.software allow-updates false

echo ">> disabling apport crash dialogs"
if [ -f /etc/default/apport ]; then
  sed -i 's/^enabled=.*/enabled=0/' /etc/default/apport
  grep -q '^enabled=' /etc/default/apport || echo 'enabled=0' >> /etc/default/apport
  echo "   /etc/default/apport -> $(grep '^enabled=' /etc/default/apport)"
fi
systemctl stop apport.service 2>/dev/null
systemctl disable apport.service 2>/dev/null

echo ">> disabling desktop autostart nags (update-notifier, gnome-software)"
AUTOSTART="/home/${KIOSK_USER}/.config/autostart"
install -d -o "$KIOSK_USER" -g "$KIOSK_USER" "$AUTOSTART"
for app in update-notifier gnome-software-service org.gnome.Software; do
  cat > "${AUTOSTART}/${app}.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=${app} (disabled for kiosk duty by kiosk-lockdown.sh)
Exec=/bin/true
Hidden=true
X-GNOME-Autostart-enabled=false
EOF
  chown "$KIOSK_USER:$KIOSK_USER" "${AUTOSTART}/${app}.desktop"
  echo "   masked ${app}"
done

echo ">> installing wmctrl (needed to keep the kiosk window on top)"
if command -v wmctrl >/dev/null 2>&1; then
  echo "   already installed"
else
  # X11 session (GDM has WaylandEnable=false here), so wmctrl works. On a
  # Wayland session it would silently do nothing — see hallkiosk's note.
  apt-get install -y wmctrl >/dev/null 2>&1 \
    && echo "   installed" \
    || echo "   WARNING: apt could not install wmctrl — the kiosk will still
   run fullscreen, it just won't force itself above other windows."
fi

echo ">> writing Firefox kiosk policies"
install -d /etc/firefox/policies
cat > /etc/firefox/policies/policies.json <<'EOF'
{
  "policies": {
    "SkipTermsOfUse": true,
    "OverrideFirstRunPage": "",
    "OverridePostUpdatePage": "",
    "DisableAppUpdate": true,
    "DontCheckDefaultBrowser": true,
    "DisableTelemetry": true,
    "NoDefaultBookmarks": true,
    "DisableFirefoxStudies": true,
    "DisableFeedbackCommands": true,
    "DisablePocket": true,
    "DisableProfileImport": true,
    "DisableSetDesktopBackground": true,
    "PromptForDownloadLocation": false,
    "DisableFirefoxAccounts": true,
    "UserMessaging": {
      "WhatsNew": false,
      "ExtensionRecommendations": false,
      "FeatureRecommendations": false,
      "UrlbarInterventions": false,
      "SkipOnboarding": true,
      "MoreFromMozilla": false
    },
    "Permissions": {
      "Notifications": { "BlockNewRequests": true, "Locked": true },
      "Location":      { "BlockNewRequests": true, "Locked": true },
      "Microphone":    { "BlockNewRequests": true, "Locked": true },
      "Autoplay":      { "Default": "allow-audio-video" }
    },
    "PopupBlocking": { "Default": true },
    "Handlers": { "mimeTypes": {} }
  }
}
EOF
echo "   /etc/firefox/policies/policies.json"

cat <<EOF

Done. Notifications are off and the kiosk will hold the top of the stack.

  Verify banners off :  sudo -u ${KIOSK_USER} DISPLAY=:0 \\
      DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/${UID_N}/bus \\
      gsettings get org.gnome.desktop.notifications show-banners   # -> false
  Restart the kiosk  :  systemctl --user restart hallkiosk   (as ${KIOSK_USER})

Some settings (autostart masking, apport) only take full effect after the next
graphical login / reboot; the notification banners take effect immediately.
EOF
