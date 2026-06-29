# HalLMediaPipe app (Jetson)

Deploy + run the **interactive** HalLMediaPipe app on the Jetson Orin Nano:
live camera feed with a real-time pose + hand skeleton and a pinch-driven UI
(buttons, bouncing spheres, the black-hole lensing mode).

This is the *app itself* — distinct from `../camera-stream/`, which is only a
headless MJPEG feed for watching the camera from the laptop.

## Requirements on the Jetson

- A **monitor** attached (the app opens a GUI window — it is not a stream).
- The **Logitech C920** on `/dev/video0`.
- System Python 3.10 with `mediapipe` + `opencv` (ship on the Yahboom image);
  `moderngl` is installed by the deploy into the user site.

## Deploy

From the laptop:

```bash
deploy/hall-app/deploy.sh          # rsync code+models, install launcher + moderngl
```

Override the target with `JETSON_HOST=jetson@<ip> deploy/hall-app/deploy.sh`.

## Run

The app is a foreground interactive program (press `q` to quit), **not** a
service — it does not auto-start, and the camera is only on while it runs (the
C920's hardware LED makes that obvious).

```bash
hallrun                                   # from a terminal on the Jetson desktop
ssh jetson@100.91.206.114 'DISPLAY=:0 ~/.local/bin/hallrun'   # over SSH, onto the monitor
```

> The C920 can't be held by two things at once. If the camera-stream is on,
> run `camctl off` first (see `../camera-stream/`).

## Remote inference (laptop camera → Jetson → laptop browser)

Run the Jetson as a headless inference appliance: your **laptop's** webcam is
the input, the Jetson does the MediaPipe + rendering, and the annotated video
comes back to your **laptop's browser**. No monitor on the Jetson.

```
laptop webcam ──MJPEG──▶ Jetson (infer + render) ──MJPEG──▶ your browser
```

One command from the laptop (after a one-time `deploy.sh`):

```bash
deploy/hall-app/remote-infer.sh        # starts everything, opens the viewer
```

It starts the laptop camera server, launches the app on the Jetson in stream
mode pointed at it, prints/open the watch URL (`http://<jetson-ip>:8092/`), and
tears it all down on Ctrl-C.

### Manual / piecewise

```bash
# 1) on the laptop — expose the webcam on the tailnet
deploy/hall-app/laptop-camera.sh                       # http://<laptop-ip>:8091/

# 2) on the Jetson — infer on that stream, serve the result headless
ssh jetson@100.91.206.114 \
  "HALL_OUTPUT=stream \
   HALL_CAMERA='http://<laptop-ip>:8091/stream.mjpg' \
   HALL_STREAM_PORT=8092 ~/.local/bin/hallrun"

# 3) on the laptop — watch
xdg-open http://100.91.206.114:8092/
```

You interact (pinch gestures, buttons, the black-hole mode) by gesturing at the
laptop camera; the UI responds in the streamed output. The lensing shader still
runs on the Jetson's GPU in this headless mode.

### Config knobs (env vars read by `src/config.py`)

| Var | Default | Meaning |
| --- | --- | --- |
| `HALL_CAMERA`        | `0`      | device index, or a stream URL to infer on |
| `HALL_OUTPUT`        | `window` | `window` (on-screen) or `stream` (headless MJPEG) |
| `HALL_STREAM_BIND`   | `auto`   | `auto` = Tailscale IP; or `0.0.0.0`; or an IP |
| `HALL_STREAM_PORT`   | `8092`   | output MJPEG port (≠ camera-stream's 8090) |
| `HALL_STREAM_QUALITY`| `80`     | output JPEG quality (1–100) |

## What runs where (CPU vs GPU)

Verified on the device (Orin Nano Super, JetPack 6.2 / L4T 36.4.3):

| Piece | Runs on |
| --- | --- |
| MediaPipe pose + hand inference (`.task`, lite) | **CPU** — MediaPipe's Python Tasks API has no CUDA/TensorRT path |
| Black-hole lensing shader (`rendering/gl_lensing.py`) | **GPU** — moderngl standalone EGL context on `NVIDIA Tegra Orin (nvgpu)`, GL 3.3 |
| Camera decode (MJPG) | CPU (OpenCV/GStreamer) |

So the interactive app runs fluidly, but the **detection itself is CPU-bound**.
Squeezing the GPU/Tensor cores for inference means leaving the MediaPipe Tasks
API and running the models via TensorRT or `onnxruntime-gpu` (both already on
the device) — that's the "make it extra-compatible" follow-up, tracked
separately.

## Notes

- Deploys to `~/HalLMediaPipe` on the Jetson; launcher symlinked into
  `~/.local/bin/hallrun`. Override the dir with `APP_DIR_REMOTE=...`.
- Uses the **system** Python on purpose: the Jetson's `mediapipe`/`opencv`
  aarch64 builds are reused rather than rebuilt under `uv` (the repo's
  `pyproject.toml` pins Python 3.12 / mediapipe 0.10.35, neither of which has a
  prebuilt aarch64 wheel — building them on-device is slow and brittle).
