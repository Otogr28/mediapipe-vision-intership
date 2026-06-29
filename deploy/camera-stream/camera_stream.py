#!/usr/bin/env python3
"""Always-on MJPEG camera stream for the Jetson (Logitech C920 on /dev/video0).

Runs as the `camera-stream` systemd service so the live feed is available
constantly over Tailscale at http://<tailscale-ip>:<port>/.

Endpoints:
    GET /              HTML page that displays the live stream full-screen
    GET /stream.mjpg   raw multipart/x-mixed-replace MJPEG stream
    GET /snapshot.jpg  single most-recent JPEG frame
    GET /healthz       "ok" + frame age, for liveness checks

Everything is configured via environment variables (see DEFAULTS below) so the
systemd unit can override without editing code. The server is deliberately
dependency-light: only OpenCV (already on the Jetson) + the stdlib.

Robustness for "constant" operation:
  * binds to the Tailscale IP by default, retrying until tailscaled is up
    (so it survives a reboot where the service starts before the tailnet);
  * re-opens the camera automatically if the USB device hiccups.
"""

import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2


# ---- configuration (env-overridable) ----------------------------------------
def _env(name, default):
    return os.environ.get(name, default)


CAM_DEVICE = _env("CAM_DEVICE", "0")          # index ("0") or path ("/dev/video0")
CAM_PORT = int(_env("CAM_PORT", "8090"))
CAM_WIDTH = int(_env("CAM_WIDTH", "1280"))
CAM_HEIGHT = int(_env("CAM_HEIGHT", "720"))
CAM_FPS = int(_env("CAM_FPS", "30"))
CAM_QUALITY = int(_env("CAM_QUALITY", "80"))  # JPEG quality 1..100
# CAM_BIND: "auto" -> the node's Tailscale IP (tailnet-only, recommended),
#           "0.0.0.0" -> every interface, or an explicit IP string.
CAM_BIND = _env("CAM_BIND", "auto")


def log(msg):
    print(msg, flush=True)


def tailscale_ip(timeout=5):
    """Return the node's first IPv4 Tailscale address, or None if unavailable."""
    try:
        out = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True, text=True, timeout=timeout,
        )
        for line in out.stdout.splitlines():
            line = line.strip()
            if line:
                return line
    except Exception:
        pass
    return None


def resolve_bind_ip():
    """Resolve the address to bind to, waiting for Tailscale if asked for 'auto'."""
    if CAM_BIND not in ("auto", "tailscale"):
        return CAM_BIND
    # Wait (up to ~2 min) for tailscaled to hand us an IP after a cold boot.
    for attempt in range(120):
        ip = tailscale_ip()
        if ip:
            return ip
        if attempt == 0:
            log("waiting for Tailscale IP (tailscaled not ready yet)...")
        time.sleep(1)
    log("WARNING: no Tailscale IP after 120s; falling back to 0.0.0.0")
    return "0.0.0.0"


def device_arg(value):
    return int(value) if value.isdigit() else value


# ---- camera capture (background grabber with auto-reopen) -------------------
class Camera:
    def __init__(self):
        self._lock = threading.Lock()
        self._jpg = None
        self._stamp = 0.0
        self._stop = False
        threading.Thread(target=self._loop, daemon=True).start()

    def _open(self):
        cap = cv2.VideoCapture(device_arg(CAM_DEVICE), cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, CAM_FPS)
        return cap

    def _loop(self):
        cap = None
        fails = 0
        while not self._stop:
            if cap is None or not cap.isOpened():
                if cap is not None:
                    cap.release()
                cap = self._open()
                if not cap.isOpened():
                    log("camera not available, retrying in 2s...")
                    time.sleep(2)
                    continue
                log("camera opened (%s @ %dx%d)" % (CAM_DEVICE, CAM_WIDTH, CAM_HEIGHT))
                fails = 0
            ok, frame = cap.read()
            if not ok:
                fails += 1
                if fails >= 30:          # ~1s of dead reads -> force a reopen
                    log("camera read failures, reopening device...")
                    cap.release()
                    cap = None
                else:
                    time.sleep(0.02)
                continue
            fails = 0
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, CAM_QUALITY])
            if ok:
                with self._lock:
                    self._jpg = buf.tobytes()
                    self._stamp = time.time()

    def latest(self):
        with self._lock:
            return self._jpg, self._stamp


# ---- HTTP server ------------------------------------------------------------
PAGE = b"""<!doctype html><html><head><meta charset="utf-8">
<title>Jetson camera - live</title>
<style>html,body{margin:0;height:100%;background:#111}
body{display:flex;justify-content:center;align-items:center}
img{max-width:100%;max-height:100vh;object-fit:contain}</style></head>
<body><img src="/stream.mjpg" alt="live camera"></body></html>"""


def make_handler(camera):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, *args):
            pass  # keep journald quiet; systemd already timestamps starts/stops

        def _frame(self):
            jpg, _ = camera.latest()
            return jpg

        def do_GET(self):
            if self.path == "/":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(PAGE)))
                self.end_headers()
                self.wfile.write(PAGE)

            elif self.path in ("/stream.mjpg", "/stream"):
                self.send_response(200)
                self.send_header(
                    "Content-Type", "multipart/x-mixed-replace; boundary=frame"
                )
                self.send_header("Cache-Control", "no-cache, private")
                self.end_headers()
                try:
                    while True:
                        jpg = self._frame()
                        if jpg is None:
                            time.sleep(0.05)
                            continue
                        self.wfile.write(
                            b"--frame\r\nContent-Type: image/jpeg\r\n"
                            b"Content-Length: " + str(len(jpg)).encode()
                            + b"\r\n\r\n" + jpg + b"\r\n"
                        )
                        time.sleep(1.0 / max(CAM_FPS, 1))
                except (BrokenPipeError, ConnectionResetError):
                    pass

            elif self.path == "/snapshot.jpg":
                jpg = self._frame()
                if jpg is None:
                    self.send_error(503, "no frame yet")
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(jpg)))
                self.end_headers()
                self.wfile.write(jpg)

            elif self.path == "/healthz":
                jpg, stamp = camera.latest()
                age = (time.time() - stamp) if stamp else -1
                body = ("ok frame_age=%.2fs\n" % age).encode()
                code = 200 if (jpg is not None and age < 5) else 503
                self.send_response(code)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            else:
                self.send_error(404)

    return Handler


def main():
    camera = Camera()
    handler = make_handler(camera)
    bind_ip = resolve_bind_ip()

    # Bind with retry: the Tailscale IP may not be assignable the instant we ask.
    server = None
    for attempt in range(60):
        try:
            server = ThreadingHTTPServer((bind_ip, CAM_PORT), handler)
            break
        except OSError as exc:
            if attempt == 0:
                log("bind %s:%d not ready (%s); retrying..." % (bind_ip, CAM_PORT, exc))
            time.sleep(1)
            if CAM_BIND in ("auto", "tailscale"):
                bind_ip = resolve_bind_ip()
    if server is None:
        log("FATAL: could not bind %s:%d" % (bind_ip, CAM_PORT))
        sys.exit(1)

    server.daemon_threads = True
    log("serving on http://%s:%d/  (hostname=%s)" % (bind_ip, CAM_PORT, socket.gethostname()))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
