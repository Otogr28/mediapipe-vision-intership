"""Output sinks: where the final annotated frame is presented.

Three interchangeable sinks, picked by `make_sink()` from config (HALL_OUTPUT):

* ``WindowSink`` — an on-screen cv2 window. Needs a display; press 'q' to quit.
* ``MjpegSink``  — a headless MJPEG HTTP server. View the annotated feed in a
  browser. This is the Jetson's *remote-inference* mode: a laptop sends its
  camera in (``HALL_CAMERA=<laptop mjpg url>``) and watches the result here, so
  the Jetson needs no monitor.
* ``WebSink``    — MjpegSink + the browser frontend: additionally serves the
  built React app (``web/dist``) and pushes the per-frame UI/gesture state
  as JSON over an SSE ``/state`` endpoint. In this mode the streamed frame
  is RAW (no cv2 drawing) — the browser renders all UI on top of it.

Keeping this out of ``main.py`` follows the project rule that the entry point
stays thin — it just calls ``sink.present(frame)`` / ``sink.should_quit()``
(plus ``sink.publish_state(...)`` in web mode).
"""

import mimetypes
import os
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2

from config import (OUTPUT_MODE, STATE_FPS, STREAM_BIND, STREAM_PORT,
                    STREAM_QUALITY, WEB_DIST_DIR)


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
        # New-frame signaling: stream clients BLOCK until a fresh JPEG
        # exists instead of polling on a fixed clock. This stops the old
        # behaviour of re-sending duplicate frames (wasted encode/decode on
        # both ends) and removes up to a frame-interval of artificial
        # latency per part — the difference is very visible on the Jetson.
        self._cond = threading.Condition()
        self._jpg = None
        self._jpg_seq = 0

        bind_ip = _resolve_bind(bind)
        self._server = ThreadingHTTPServer((bind_ip, port), self._make_handler())
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        print("serving annotated feed on http://%s:%d/  (hostname=%s)"
              % (bind_ip, port, socket.gethostname()), flush=True)

    def present(self, frame):
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self._quality])
        if ok:
            with self._cond:
                self._jpg = buf.tobytes()
                self._jpg_seq += 1
                self._cond.notify_all()

    def should_quit(self):
        # Headless service: runs until SIGINT/SIGTERM (handled in main()).
        return False

    def close(self):
        self._server.shutdown()

    def _latest(self):
        with self._cond:
            return self._jpg

    def _wait_frame(self, last_seq, timeout=1.0):
        """Block until a JPEG newer than ``last_seq`` exists (or timeout).
        Returns ``(jpg, seq)`` — same seq as passed means nothing new."""
        with self._cond:
            self._cond.wait_for(
                lambda: self._jpg is not None and self._jpg_seq != last_seq,
                timeout=timeout,
            )
            return self._jpg, self._jpg_seq

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
                        last_seq = 0
                        while True:
                            jpg, seq = sink._wait_frame(last_seq)
                            if jpg is None or seq == last_seq:
                                continue  # timeout tick — no new frame yet
                            last_seq = seq
                            self.wfile.write(
                                b"--frame\r\nContent-Type: image/jpeg\r\n"
                                b"Content-Length: " + str(len(jpg)).encode()
                                + b"\r\n\r\n" + jpg + b"\r\n"
                            )
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


# Shown at "/" in web mode when web/dist has not been built yet.
_NO_DIST_PAGE = b"""<!doctype html><html><head><meta charset="utf-8">
<title>HalLMediaPipe - frontend not built</title>
<style>html,body{margin:0;height:100%;background:#111;color:#ddd;
font:16px/1.6 system-ui,sans-serif}body{display:flex;justify-content:center;
align-items:center}code{background:#222;padding:2px 6px;border-radius:4px}
</style></head><body><div><h2>Frontend not built</h2>
<p>The backend is running in web mode, but <code>web/dist</code> is missing.</p>
<p>Build it with <code>cd web &amp;&amp; npm run build</code>, or develop
against this backend with <code>npm run dev</code>.</p>
<p>The raw feed is still available at <a href="/stream.mjpg"
style="color:#6cf">/stream.mjpg</a>.</p></div></body></html>"""


class WebSink(MjpegSink):
    """MjpegSink + the web frontend.

    Adds two things to the MJPEG server:

    * ``GET /state`` — an SSE stream pushing the latest per-frame UI state
      JSON (built by ``web/state.py``) at up to ``STATE_FPS`` events/s. The
      same latest-only pattern as the MJPEG loop: a slow client skips
      snapshots instead of building a backlog.
    * Static serving of the built frontend (``web/dist``) at ``/``.

    ``present()`` still streams the frame — but ``main.py`` passes the RAW
    flipped frame in web mode, so the browser composites all UI itself.
    """

    def __init__(self, bind="auto", port=8092, quality=80, fps=30,
                 state_fps=STATE_FPS, dist_dir=WEB_DIST_DIR):
        # Set before super().__init__ — the HTTP server starts serving in
        # there, and its handler reads these through the `sink` closure.
        self._state_fps = max(int(state_fps), 1)
        self._dist_dir = os.path.realpath(dist_dir) if dist_dir else None
        self._state = None       # latest state JSON (bytes)
        self._state_seq = 0
        super().__init__(bind=bind, port=port, quality=quality, fps=fps)

    def publish_state(self, data):
        """Store this frame's state JSON (bytes) for /state clients.

        ``main.py`` calls this once per frame right after ``ui.update``;
        the presence of this method is also how it detects web mode.
        """
        with self._lock:
            self._state = data
            self._state_seq += 1

    def _latest_state(self):
        with self._lock:
            return self._state, self._state_seq

    def _make_handler(self):
        base_handler = super()._make_handler()
        sink = self

        class Handler(base_handler):

            def do_GET(self):
                path = self.path.split("?", 1)[0]
                if path == "/state":
                    self._serve_state()
                elif path in ("/stream.mjpg", "/stream", "/snapshot.jpg",
                              "/healthz"):
                    base_handler.do_GET(self)
                else:
                    self._serve_static(path)

            def _serve_state(self):
                """SSE loop — same latest-only shape as the MJPEG stream."""
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache, private")
                self.end_headers()
                last_seq = 0
                try:
                    while True:
                        data, seq = sink._latest_state()
                        if data is None or seq == last_seq:
                            time.sleep(0.01)
                            continue
                        last_seq = seq
                        self.wfile.write(b"data: " + data + b"\n\n")
                        time.sleep(1.0 / sink._state_fps)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def _serve_static(self, path):
                """Serve the built frontend, path-traversal-safe."""
                root = sink._dist_dir
                if path == "/":
                    path = "/index.html"
                if root is not None:
                    full = os.path.realpath(
                        os.path.join(root, path.lstrip("/")))
                    inside = full == root or full.startswith(root + os.sep)
                    if inside and os.path.isfile(full):
                        ctype = (mimetypes.guess_type(full)[0]
                                 or "application/octet-stream")
                        with open(full, "rb") as f:
                            self._send(200, ctype, f.read())
                        return
                if path == "/index.html":
                    # dist/ not built yet — explain instead of a bare 404.
                    self._send(200, "text/html; charset=utf-8", _NO_DIST_PAGE)
                    return
                self.send_error(404)

        return Handler


def make_sink(frame_w, frame_h):
    """Build the output sink selected by config (HALL_OUTPUT)."""
    if OUTPUT_MODE == "web":
        return WebSink(bind=STREAM_BIND, port=STREAM_PORT,
                       quality=STREAM_QUALITY)
    if OUTPUT_MODE == "stream":
        return MjpegSink(bind=STREAM_BIND, port=STREAM_PORT, quality=STREAM_QUALITY)
    return WindowSink("Camera", frame_w, frame_h)
