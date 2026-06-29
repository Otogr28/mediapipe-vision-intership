"""Output sinks: where the final annotated frame is presented.

Two interchangeable sinks, picked by `make_sink()` from config (HALL_OUTPUT):

* ``WindowSink`` — an on-screen cv2 window. Needs a display; press 'q' to quit.
* ``MjpegSink``  — a headless MJPEG HTTP server. View the annotated feed in a
  browser. This is the Jetson's *remote-inference* mode: a laptop sends its
  camera in (``HALL_CAMERA=<laptop mjpg url>``) and watches the result here, so
  the Jetson needs no monitor.

Keeping this out of ``main.py`` follows the project rule that the entry point
stays thin — it just calls ``sink.present(frame)`` / ``sink.should_quit()``.
"""

import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2

from config import OUTPUT_MODE, STREAM_BIND, STREAM_PORT, STREAM_QUALITY


class WindowSink:
    """Presents frames in a resizable on-screen window."""

    def __init__(self, title, frame_w, frame_h):
        self._title = title
        # WINDOW_NORMAL makes the window resizable/maximizable; the frame is
        # scaled by the window manager, so capture/UI logic keep working in
        # camera-frame coordinates.
        cv2.namedWindow(title, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(title, frame_w, frame_h)

    def present(self, frame):
        cv2.imshow(self._title, frame)

    def should_quit(self):
        return (cv2.waitKey(1) & 0xFF) == ord("q")

    def close(self):
        cv2.destroyAllWindows()


def _tailscale_ip(timeout=5):
    """The node's first IPv4 Tailscale address, or None if unavailable."""
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


def _resolve_bind(bind):
    if bind not in ("auto", "tailscale"):
        return bind
    ip = _tailscale_ip()
    if ip is None:
        print("WARNING: no Tailscale IP; binding 0.0.0.0", flush=True)
    return ip or "0.0.0.0"


_PAGE = b"""<!doctype html><html><head><meta charset="utf-8">
<title>HalLMediaPipe - remote inference</title>
<style>html,body{margin:0;height:100%;background:#111}
body{display:flex;justify-content:center;align-items:center}
img{max-width:100%;max-height:100vh;object-fit:contain}</style></head>
<body><img src="/stream.mjpg" alt="inference output"></body></html>"""


class MjpegSink:
    """Serves the most-recent annotated frame as MJPEG over HTTP.

    Endpoints: ``/`` (viewer page), ``/stream.mjpg`` (raw MJPEG),
    ``/snapshot.jpg`` (latest frame), ``/healthz`` (liveness).
    """

    def __init__(self, bind="auto", port=8092, quality=80, fps=30):
        self._quality = int(quality)
        self._fps = max(int(fps), 1)
        self._lock = threading.Lock()
        self._jpg = None

        bind_ip = _resolve_bind(bind)
        self._server = ThreadingHTTPServer((bind_ip, port), self._make_handler())
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        print("serving annotated feed on http://%s:%d/  (hostname=%s)"
              % (bind_ip, port, socket.gethostname()), flush=True)

    def present(self, frame):
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self._quality])
        if ok:
            with self._lock:
                self._jpg = buf.tobytes()

    def should_quit(self):
        # Headless service: runs until SIGINT/SIGTERM (handled in main()).
        return False

    def close(self):
        self._server.shutdown()

    def _latest(self):
        with self._lock:
            return self._jpg

    def _make_handler(self):
        sink = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *args):
                pass

            def _send(self, code, ctype, body):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/":
                    self._send(200, "text/html; charset=utf-8", _PAGE)

                elif self.path in ("/stream.mjpg", "/stream"):
                    self.send_response(200)
                    self.send_header(
                        "Content-Type", "multipart/x-mixed-replace; boundary=frame"
                    )
                    self.send_header("Cache-Control", "no-cache, private")
                    self.end_headers()
                    try:
                        while True:
                            jpg = sink._latest()
                            if jpg is None:
                                time.sleep(0.05)
                                continue
                            self.wfile.write(
                                b"--frame\r\nContent-Type: image/jpeg\r\n"
                                b"Content-Length: " + str(len(jpg)).encode()
                                + b"\r\n\r\n" + jpg + b"\r\n"
                            )
                            time.sleep(1.0 / sink._fps)
                    except (BrokenPipeError, ConnectionResetError):
                        pass

                elif self.path == "/snapshot.jpg":
                    jpg = sink._latest()
                    if jpg is None:
                        self.send_error(503, "no frame yet")
                        return
                    self._send(200, "image/jpeg", jpg)

                elif self.path == "/healthz":
                    jpg = sink._latest()
                    body = b"ok\n" if jpg is not None else b"no-frame\n"
                    self._send(200 if jpg is not None else 503, "text/plain", body)

                else:
                    self.send_error(404)

        return Handler


def make_sink(frame_w, frame_h):
    """Build the output sink selected by config (HALL_OUTPUT)."""
    if OUTPUT_MODE == "stream":
        return MjpegSink(bind=STREAM_BIND, port=STREAM_PORT, quality=STREAM_QUALITY)
    return WindowSink("Camera", frame_w, frame_h)
