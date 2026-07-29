import fcntl
import glob
import os
import re
import struct
import sys
import threading
import time

import cv2


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

    def __init__(self, capture, loop=False, fps=0.0):
        self._cap = capture
        # loop + fps are for VIDEO-FILE sources (testing: drive the app from a
        # recorded clip). loop rewinds at EOF; fps paces the reader to the
        # clip's native rate so motion plays back at real speed. A live webcam
        # or network stream leaves both off (read as fast as frames arrive).
        self._loop = loop
        self._interval = 1.0 / fps if fps and fps > 0 else 0.0
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
            t0 = time.monotonic()
            ok, frame = self._cap.read()
            if not ok or frame is None:
                # End of a video file: rewind and keep playing (test loop).
                if self._loop:
                    self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
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
            # Pace a file source to its native fps so it plays at real speed
            # (a webcam/stream leaves _interval at 0 → read flat out).
            if self._interval:
                dt = self._interval - (time.monotonic() - t0)
                if dt > 0:
                    time.sleep(dt)

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


# --- camera selection -------------------------------------------------------
# A webcam's /dev/video<N> number is not a property of the camera: it comes
# from enumeration order, and a modern UVC camera claims TWO consecutive nodes
# — the capture node and a metadata node that opens fine and then delivers
# nothing. Swapping the exhibit's C920 for an MX Brio left the Brio on
# /dev/video1+2 with no /dev/video0 at all, so the app's hardcoded index 0
# failed to open and the kiosk crash-looped. Nobody is standing at the exhibit
# to edit an env var when that happens (it updates itself from git), so the app
# asks the kernel which nodes can actually capture instead of trusting a number.

_V4L2_CAP_VIDEO_CAPTURE = 0x00000001
# VIDIOC_QUERYCAP = _IOR('V', 0, struct v4l2_capability); the struct is 104
# bytes, of which we want two u32s: capabilities (device-wide) and device_caps
# (THIS node — what separates a capture node from a metadata one).
_VIDIOC_QUERYCAP = 0x80685600
_QUERYCAP_SIZE = 104
_CAPS_OFFSET = 84

_STREAM_SCHEMES = ("http://", "https://", "rtsp://", "udp://", "tcp://")
_DEVICE_PATH_RE = re.compile(r"/dev/video(\d+)\Z")


def node_captures_video(path):
    """True if this ``/dev/video*`` node reports a video-capture capability.

    The check is a single ioctl — no streaming is started, so it is safe to
    run against a node another process is already using.
    """
    try:
        fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
    except OSError:
        return False
    try:
        buf = bytearray(_QUERYCAP_SIZE)
        fcntl.ioctl(fd, _VIDIOC_QUERYCAP, buf, True)
        caps, device_caps = struct.unpack_from("<II", buf, _CAPS_OFFSET)
        # device_caps is zero on kernels older than 3.4; fall back to the
        # device-wide capabilities there (worst case we pick a metadata node
        # on an ancient kernel, which is not one we ever run on).
        return bool((device_caps or caps) & _V4L2_CAP_VIDEO_CAPTURE)
    except (OSError, struct.error):
        return False
    finally:
        os.close(fd)


def list_capture_devices():
    """Indices of every ``/dev/video*`` node that can deliver frames, ascending."""
    found = []
    for path in glob.glob("/dev/video*"):
        match = _DEVICE_PATH_RE.match(path)
        if match and node_captures_video(path):
            found.append(int(match.group(1)))
    return sorted(found)


def resolve_camera_source(value):
    """Turn a HALL_CAMERA value into ``(source, kind)`` for ``VideoCapture``.

    ``kind`` is ``"v4l2"`` for a local webcam (which ``main.py`` opens through
    the V4L2 backend with an explicit MJPG mode), ``"stream"`` for a network
    URL, or ``"file"`` for a recorded clip — the last two go to OpenCV's
    default backend untouched.

    A bare index is CHECKED against the kernel: when ``/dev/video<N>`` is
    missing or is a metadata-only node, the first real capture node stands in
    and the substitution is printed. An explicit ``/dev/videoN`` path is
    honoured as given, so a machine with two cameras can still pin one.
    """
    text = str(value)
    if text.startswith(_STREAM_SCHEMES):
        return text, "stream"
    if _DEVICE_PATH_RE.match(text):
        return text, "v4l2"
    if not text.isdigit():
        return text, "file"

    index = int(text)
    if sys.platform != "linux":
        return index, "v4l2"
    if node_captures_video("/dev/video%d" % index):
        return index, "v4l2"
    available = list_capture_devices()
    if not available:
        print("No V4L2 capture device found — is the camera plugged in?")
        return index, "v4l2"
    print("Camera %d is not a capture device; using /dev/video%d instead"
          % (index, available[0]))
    return available[0], "v4l2"
