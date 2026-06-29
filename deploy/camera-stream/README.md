# Camera stream (Jetson)

Always-available live MJPEG feed of the Jetson's camera (Logitech C920 on
`/dev/video0`), reachable over **Tailscale** — with a privacy on/off switch so
the camera only streams when you want it to.

## What it is

- `camera_stream.py` — a tiny, dependency-light MJPEG server (OpenCV + stdlib).
  Binds to the node's **Tailscale IP** by default (tailnet-only, not exposed on
  the lab WiFi), re-opens the camera if the USB device hiccups, and waits for
  Tailscale on a cold boot.
- `camera-stream.service` — systemd unit that runs it as the `jetson` user.
- `camctl` — the on/off switch (`on` / `off` / `status`).
- `camera-stream.sudoers` — a **scoped** passwordless sudo rule so `camctl`
  toggles the service without a password (nothing else is granted).
- `install.sh` — installs all of the above on the Jetson (run with `sudo`).
- `deploy.sh` — pushes the files from the laptop and runs the installer.

## Endpoints

| URL | What |
| --- | --- |
| `http://<ip>:8090/`             | full-screen live view (open in a browser) |
| `http://<ip>:8090/stream.mjpg`  | raw MJPEG stream (embed in an `<img>`) |
| `http://<ip>:8090/snapshot.jpg` | single most-recent frame |
| `http://<ip>:8090/healthz`      | `ok` + frame age (liveness) |

`<ip>` is the Jetson's Tailscale IP — currently `100.91.206.114`.

## Deploy

From the laptop, in this directory:

```bash
./deploy.sh                       # copies files + runs the installer (asks for the Jetson sudo password once)
```

After install the stream is **OFF** (privacy default) and will **not** start on
boot. Nothing is captured until you turn it on.

## Privacy on/off switch

From the Jetson, or from the laptop via `ssh jetson@100.91.206.114 …`:

```bash
camctl on        # start streaming now AND auto-start on boot
camctl off       # stop now AND stay off on boot   <-- lab privacy
camctl status    # active? on-boot?
```

`on`/`off` are passwordless (scoped sudoers rule). The C920 has a hardware LED
that lights whenever the camera is in use, so it's physically obvious when the
stream is live.

> Design note: `on` is "constant" — it survives reboots until you turn it
> `off`. `off` is sticky too, so a forgotten reboot never silently re-enables
> the camera.

## Configuration

Defaults live in `camera-stream.service` as `Environment=` lines; edit and
`sudo systemctl daemon-reload && camctl off && camctl on` to apply.

| Var | Default | Meaning |
| --- | --- | --- |
| `CAM_DEVICE`  | `0`     | camera index or `/dev/videoN` |
| `CAM_PORT`    | `8090`  | HTTP port |
| `CAM_WIDTH`   | `1280`  | capture width |
| `CAM_HEIGHT`  | `720`   | capture height |
| `CAM_FPS`     | `30`    | capture / stream FPS |
| `CAM_QUALITY` | `80`    | JPEG quality (1–100) |
| `CAM_BIND`    | `auto`  | `auto` = Tailscale IP; or `0.0.0.0`; or an explicit IP |

## Laptop shortcut (navi)

A navi cheat (`hall-camera.cheat`, symlinked into `~/.local/share/navi/cheats/`)
gives one-key actions: turn on & watch, turn off, status, snapshot, deploy.
Run `navi` and search "hall camera".
