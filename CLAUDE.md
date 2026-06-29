# HalLMediaPipe — Claude Code Guidelines

## Project structure

```
src/
  main.py               — entry point: camera loop only, no UI logic
  config.py             — global constants (camera source, thresholds, …)
  output.py             — output sinks: on-screen window or headless MJPEG stream
  detection/
    detectors.py        — MediaPipe pose/hand detector setup + shared results
  rendering/
    drawing.py          — landmark/connection drawing helpers
  ui/
    manager.py          — all UI state, buttons, and interactable objects
    button.py           — Button widget (hand-pinch interaction)
    interactables.py    — physics objects (BouncingSphere, …)
```

## Modularity preference

Keep `main.py` thin: camera capture, detector calls, and drawing landmarks only.
All UI logic (state machine, button layout, scene objects) belongs in `ui/manager.py` or dedicated modules — never inline in `main.py`.

When adding a new mode or feature:
- New UI state → add it to `UIManager` in `ui/manager.py`
- New interactable object type → add it to `ui/interactables.py`
- New button widget behavior → add it to `ui/button.py`

## Hardware — Jetson Orin Nano (deployment target)

The Jetson Orin Nano Developer Kit (Yahboom kit) is the edge device this project runs on. Set up 2026-06-24.

- **Boots from the internal NVMe**, which ships pre-loaded with a Yahboom JetPack 6.2 image (L4T / UEFI-QSPI firmware 36.4.3). A spare bootable JetPack 6.2 image lives on the 128 GB SSK USB SSD (`dd` of the official `sd-blob.img` from `jp62-orin-nano-sd-card-image.zip`), usable as a recovery boot via the UEFI Boot Manager (ESC at the NVIDIA splash).
- **Default login:** user `jetson`, hostname `yahboom`. Password (Yahboom vendor default, same for `sudo`) is in the gitignored `SECRETS.local.md`.
- **Access from the dev laptop over USB (headless):** plug the Jetson's USB-C into the laptop. L4T's USB device-mode networking brings the board up at `192.168.55.1` (host side gets `192.168.55.100`) with SSH open — no WiFi/Ethernet needed: `ssh jetson@192.168.55.1`. Good for `scp` deploys and remote shells.
- **WiFi:** Realtek RTL8822CE, interface `wlP1p1s0`. The board ships with WiFi **rfkill soft-blocked and disabled in NetworkManager**. Enable once with `sudo rfkill unblock all && sudo nmcli radio wifi on` (over SSH, plain `nmcli radio wifi on` fails with a polkit "Not authorized" error — must use `sudo`). It is joined to **GordonNET** (WPA2-Enterprise, EAP PEAP / phase2 MSCHAPv2, no CA cert; identity in `SECRETS.local.md`) with autoconnect on, so it reconnects on boot and pulls a DHCP lease (172.24.x.x/16). The enterprise password is stored only in the board's NetworkManager config, not here.

## Language

All code, comments, and commit messages are written in English.
