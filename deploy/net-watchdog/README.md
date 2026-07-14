# net-watchdog — keep the Jetson reachable over Tailscale

The Jetson kept "disappearing" from Tailscale after sitting idle (it looked
offline for days, then came back on a reboot). The cause was **not** Tailscale
— it was the **WiFi radio's power-save**. The board's Realtek `rtl8822ce`
(vendor out-of-tree driver) sleeps the radio when idle, which tears down the
Tailscale NAT/DERP mapping; with no inbound traffic to wake it, the node stays
unreachable until something forces the link back up.

This package fixes the root cause and adds a safety net.

## What it installs

1. **WiFi power-save OFF (root-cause fix), belt-and-suspenders:**
   - `802-11-wireless.powersave 2` (disable) on every saved WiFi connection.
   - a NetworkManager dispatcher hook
     (`/etc/NetworkManager/dispatcher.d/99-hall-wifi-powersave-off`) that runs
     `iw dev <dev> set power_save off` on every link-up — the vendor driver
     often ignores the NM property, so this is the reliable layer.
2. **A connectivity watchdog** (`/opt/hall-net-watchdog/net-watchdog.sh`) on a
   systemd timer (`hall-net-watchdog.timer`, every 2 min + 30 s after boot):
   - re-asserts power-save off,
   - probes the internet (a 204 captive-portal check — this traffic *also*
     keeps the radio awake, so the watchdog doubles as a keepalive),
   - if internet is down: re-activates the WiFi connection, then restarts
     NetworkManager,
   - if Tailscale isn't `Running` + `Self.Online`: `tailscale up`, then
     restarts `tailscaled` as a last resort.

Everything runs as root from the timer. Healthy runs are cheap (one probe).

## Install / update

From the **laptop** (over Tailscale):

```bash
JETSON_HOST=yahboom deploy/net-watchdog/deploy.sh
```

rsyncs this dir to the Jetson and runs `install.sh` under sudo. Re-run any time
to update the script (idempotent). To install **on the Jetson** directly:

```bash
sudo deploy/net-watchdog/install.sh
```

## Check it

```bash
systemctl status hall-net-watchdog.timer          # armed + next fire
journalctl -u hall-net-watchdog.service -f        # live (volatile) log
sudo tail -f /var/log/hall-net-watchdog.log       # history (survives reboots)
iw dev wlP1p1s0 get power_save                     # must say: Power save: off
```

Verified 2026-07-14: a forced `tailscale down` was detected and healed
(`tailscale up` → daemon restart → `OK tailscale recovered`) within ~5 s, and
power-save stays off across reassociation.

## Tuning

Override via a systemd drop-in on `hall-net-watchdog.service`
(`WD_WIFI_DEV`, `WD_TIMEOUT`, `WD_LOG`), or change the cadence in
`hall-net-watchdog.timer` (`OnUnitActiveSec`). The WiFi device auto-detects
(first `wifi` device from `nmcli`), falling back to `wlP1p1s0`.
