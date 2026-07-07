import threading
import time


class FreshestFrame:
    """Threaded camera reader that always hands back the *most recent* frame.

    OpenCV's ``VideoCapture`` keeps a small queue of frames in the driver. When
    the consumer (our render loop) is slower than the camera's frame rate — the
    common case here: the CPU-bound MediaPipe pose caps the loop well under the
    camera's 25-30 fps — that queue fills and ``read()`` hands back
    progressively older frames. The lag then grows without bound; that backlog,
    not the capture itself, is the "camera delay".

    This wrapper runs the capture in a background thread that grabs frames as
    fast as they arrive and keeps only the latest one. The main loop reads that
    latest frame, so stale frames are *dropped* instead of queued and the
    end-to-end latency stays at ~1 frame no matter how slow the loop runs.

    It exposes the small slice of the ``VideoCapture`` API ``main.py`` uses
    (``read``/``isOpened``/``release``), so it drops in as a wrapper around an
    already-configured capture.
    """

    def __init__(self, capture):
        self._cap = capture
        self._lock = threading.Lock()
        self._frame = None
        self._ok = False
        self._running = True
        # Monotonic instant the newest frame ARRIVED — lets the main loop
        # detect a stalled camera (driver wedge: reads stop returning but
        # nothing errors) and bail out so the supervisor can restart it.
        self._last_frame_t = time.monotonic()
        # daemon=True so a stuck reader can never keep the process alive.
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self):
        while self._running:
            ok, frame = self._cap.read()
            if not ok or frame is None:
                # A network source (or a momentarily starved webcam) can return
                # nothing transiently; keep polling rather than giving up.
                continue
            # ``read()`` allocates a fresh array each call, so publishing the
            # reference (no copy) is safe: the main loop flips it into a new
            # array before drawing, and the reader never mutates a published
            # frame in place.
            with self._lock:
                self._frame = frame
                self._ok = True
                self._last_frame_t = time.monotonic()

    def frame_age(self):
        """Seconds since the last NEW frame arrived from the camera."""
        with self._lock:
            return time.monotonic() - self._last_frame_t

    def read(self):
        """Return ``(ok, frame)`` for the freshest frame, like VideoCapture."""
        with self._lock:
            if not self._ok or self._frame is None:
                return False, None
            return True, self._frame

    def isOpened(self):
        return self._cap.isOpened()

    def release(self):
        self._running = False
        self._thread.join(timeout=1.0)
        self._cap.release()
