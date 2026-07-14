"""GPU/ONNX hand-landmark backend.

An alternative to MediaPipe's HandLandmarker that runs the same two-stage hand
pipeline (palm detection -> hand landmark) through onnxruntime, so it can use
the CUDA execution provider on the Jetson (with CPU fallback elsewhere). It is
selected by ``HALL_INFERENCE=gpu`` in config; the MediaPipe path stays the
default. POSE is unaffected (it remains MediaPipe in both modes).

The detector emits result objects that are drop-in compatible with what the
app already consumes from MediaPipe's HandLandmarkerResult:

* ``result.hand_landmarks`` -> list (one entry per detected hand) of lists of
  21 landmark objects, each with ``.x`` / ``.y`` normalized to [0, 1] in frame
  coords (plus ``.z`` and ``.visibility``; visibility is None, which the
  drawing code treats as "always draw").
* ``result.handedness`` -> list parallel to ``hand_landmarks``; element [0] is
  a category object with ``.category_name`` in {"Left", "Right"} and ``.score``.

When no hands are detected the result has empty (not None) lists, matching
MediaPipe. The very first frames before any inference completes leave the
module global as None (same as MediaPipe's async callback).

onnxruntime is imported lazily (inside the vendored ``_zoo`` classes), so the
default MediaPipe path does not require onnxruntime to be installed.
"""

import threading
import traceback

import cv2
import numpy as np

from config import (HAND_ONNX, HAND_ROI_TRACKING,
                    MIN_HAND_DETECTION_CONFIDENCE, NUM_HANDS, ONNX_PROVIDERS,
                    PALM_ONNX)

# Hand-landmark indices that make up the palm-detector keypoint set, in the
# exact order MPHandPose.PALM_LANDMARK_IDS expects (wrist, the four finger
# MCPs, thumb CMC, thumb MCP) — used to synthesize a palm-detection row from
# the previous frame's landmarks for ROI tracking.
_PALM_LANDMARK_IDS = np.array([0, 5, 9, 13, 17, 1, 2])


def _palm_from_landmarks(screen_landmarks):
    """Build a palm-detector-format row [bbox(4), 7 keypoints(14), score]
    from a previous frame's 21 screen landmarks (pixels). The keypoints are
    the same hand landmarks MPHandPose reads for crop rotation, so the
    crop/rotate math sees exactly the geometry it expects."""
    pts = screen_landmarks[_PALM_LANDMARK_IDS, :2]
    x1, y1 = pts.min(axis=0)
    x2, y2 = pts.max(axis=0)
    return np.concatenate([[x1, y1, x2, y2], pts.reshape(-1), [1.0]]).astype(np.float32)


def _center_in_bbox(palm, bbox):
    """True when a palm detection's bbox centre lies inside a tracked hand's
    bbox — i.e. the detector re-found a hand we are already tracking."""
    cx = (palm[0] + palm[2]) / 2
    cy = (palm[1] + palm[3]) / 2
    x1, y1, x2, y2 = bbox
    return x1 <= cx <= x2 and y1 <= cy <= y2

# --- result shim classes (attribute-compatible with mediapipe's result) ----

class _Landmark:
    """One landmark. Mirrors mediapipe's NormalizedLandmark attribute surface.

    ``visibility`` / ``presence`` default to None; the drawing helpers treat a
    None visibility as "always draw" (hand landmarks have no visibility in
    MediaPipe either).
    """

    __slots__ = ("x", "y", "z", "visibility", "presence")

    def __init__(self, x, y, z=0.0, visibility=None, presence=None):
        self.x = x
        self.y = y
        self.z = z
        self.visibility = visibility
        self.presence = presence


class _Category:
    """A handedness category. Mirrors mediapipe's Category attribute surface."""

    __slots__ = ("category_name", "score", "index", "display_name")

    def __init__(self, category_name, score, index=0, display_name=None):
        self.category_name = category_name
        self.score = score
        self.index = index
        self.display_name = display_name if display_name is not None else category_name


class _HandResult:
    """Stand-in for mediapipe's HandLandmarkerResult.

    Only the two fields the app reads are populated: ``hand_landmarks`` and
    ``handedness`` (parallel lists). ``hand_world_landmarks`` is provided too
    for completeness but is not consumed by the app today.
    """

    __slots__ = ("hand_landmarks", "handedness", "hand_world_landmarks")

    def __init__(self, hand_landmarks, handedness, hand_world_landmarks=None):
        self.hand_landmarks = hand_landmarks
        self.handedness = handedness
        self.hand_world_landmarks = hand_world_landmarks or []


class GpuHandDetector:
    """Two-stage ONNX hand detector with a MediaPipe-compatible interface.

    Exposes ``detect_async(image, timestamp_ms)`` and ``close()`` so it is a
    drop-in for the MediaPipe HandLandmarker that ``main.py`` drives. Inference
    runs on a background worker thread (like MediaPipe's LIVE_STREAM mode):
    ``detect_async`` just hands the latest frame to the worker and returns
    immediately, so it never blocks the camera/draw loop. The worker always
    processes the *most recent* submitted frame (older ones are dropped), and
    on completion hands the result to ``result_callback`` exactly like
    MediaPipe's async callback, which stores it into
    ``detectors.latest_hand_result``.

    Hands are ROI-TRACKED across frames (config.HAND_ROI_TRACKING): once a
    hand is landmarked, the next frame's crop comes from its own landmarks
    and the palm detector only runs to fill empty hand slots — this is what
    keeps a hand tracked near the frame edge, where a partially visible palm
    stops being detectable long before the landmarks stop being trackable.
    """

    def __init__(
        self,
        result_callback,
        palm_path=PALM_ONNX,
        hand_path=HAND_ONNX,
        providers=None,
        num_hands=NUM_HANDS,
        palm_score_threshold=MIN_HAND_DETECTION_CONFIDENCE,
        hand_conf_threshold=MIN_HAND_DETECTION_CONFIDENCE,
    ):
        # Imported here (not at module top) so building this detector is what
        # pulls in onnxruntime + the vendored classes; the MediaPipe default
        # path never touches them.
        from detection._zoo.mp_handpose import MPHandPose
        from detection._zoo.mp_palmdet import MPPalmDet

        providers = list(providers) if providers is not None else list(ONNX_PROVIDERS)

        self._result_callback = result_callback
        self._num_hands = num_hands
        self._palm = MPPalmDet(
            palm_path,
            scoreThreshold=palm_score_threshold,
            providers=providers,
        )
        self._handpose = MPHandPose(
            hand_path,
            confThreshold=hand_conf_threshold,
            providers=providers,
        )

        # ROI tracking state (worker thread only): one entry per hand that was
        # successfully landmarked last frame — {"palm": synthetic palm row for
        # this frame's crop, "bbox": last enlarged hand bbox for dedup against
        # fresh palm detections}. See config.HAND_ROI_TRACKING.
        self._roi_tracking = HAND_ROI_TRACKING
        self._tracked = []

        # Background inference worker. detect_async drops the latest frame into
        # `_pending` and signals `_wakeup`; the worker processes the most recent
        # frame and drops any it couldn't keep up with — so the main loop is
        # never blocked by inference.
        self._lock = threading.Lock()
        self._pending = None          # (bgr, frame_w, frame_h, timestamp_ms)
        self._wakeup = threading.Event()
        self._stop = False
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def detect_async(self, image, timestamp_ms=None):
        """Hand the latest frame to the worker thread (non-blocking).

        ``image`` is a ``mediapipe.Image`` (as built by ``toMpImage``), so its
        ``numpy_view()`` is an RGB ndarray. The vendored reference pipeline
        expects BGR, so convert here (also yielding an owned copy that is safe
        to hand to the worker thread) and return immediately.
        """
        bgr = cv2.cvtColor(image.numpy_view(), cv2.COLOR_RGB2BGR)
        frame_h, frame_w = bgr.shape[:2]
        with self._lock:
            self._pending = (bgr, frame_w, frame_h, timestamp_ms)
        self._wakeup.set()

    def _run(self):
        """Worker loop: process the most recent submitted frame, drop the rest."""
        while True:
            self._wakeup.wait()
            self._wakeup.clear()
            if self._stop:
                return
            with self._lock:
                job = self._pending
                self._pending = None
            if job is None:
                continue
            bgr, frame_w, frame_h, timestamp_ms = job
            try:
                result = self._infer(bgr, frame_w, frame_h)
            except Exception:
                # A bad frame must not kill the worker; log and keep serving.
                traceback.print_exc()
                continue
            # Mimic MediaPipe's async callback contract (result, image, timestamp).
            self._result_callback(result, None, timestamp_ms)

    def _infer(self, bgr, frame_w, frame_h):
        # ROI tracking (MediaPipe's own scheme): a hand successfully
        # landmarked last frame is re-cropped this frame from its own
        # landmarks; the palm detector only runs to fill remaining hand
        # slots. Near the frame edge this is the difference between keeping
        # the hand and losing it — a partially visible palm falls below the
        # detector's threshold long before the landmark model loses track.
        rois = [t["palm"] for t in self._tracked]
        tracked_bboxes = [t["bbox"] for t in self._tracked]

        if len(rois) < self._num_hands:
            # ndarray (N, 19): [bbox(4), lmk(14), score].
            palms = self._palm.infer(bgr)
            if palms is not None and len(palms) > 0:
                order = np.argsort(palms[:, -1])[::-1]
                for idx in order:
                    if len(rois) >= self._num_hands:
                        break
                    palm = palms[idx]
                    # Skip detections of hands we are already tracking.
                    if any(_center_in_bbox(palm, bb) for bb in tracked_bboxes):
                        continue
                    rois.append(palm)

        hand_landmarks = []
        handedness = []
        hand_world_landmarks = []
        new_tracked = []

        for palm in rois:
            res = self._handpose.infer(bgr, palm)
            if res is None:  # below confidence threshold -> track dropped too
                continue

            # res layout (see mp_handpose._postprocess):
            #   [0:4]   hand bbox (px)
            #   [4:67]  21 screen landmarks (x,y,z) in IMAGE PIXELS
            #   [67:130] 21 world landmarks
            #   [130]   handedness (0=left .. 1=right)
            #   [131]   confidence
            screen = res[4:67].reshape(21, 3)
            world = res[67:130].reshape(21, 3)
            handed_score = float(res[130])

            lms = [
                # Normalize pixel coords to [0, 1]. z is in the same pixel
                # scale as x/y (relative to the wrist), so normalize it by
                # width to keep it on roughly the same scale as MediaPipe's
                # z (the app does not currently use z, so exact scale is not
                # load-bearing).
                _Landmark(
                    x=float(px) / frame_w,
                    y=float(py) / frame_h,
                    z=float(pz) / frame_w,
                )
                for px, py, pz in screen
            ]
            hand_landmarks.append(lms)

            world_lms = [
                _Landmark(x=float(wx), y=float(wy), z=float(wz))
                for wx, wy, wz in world
            ]
            hand_world_landmarks.append(world_lms)

            # Stable, consistent handedness keying (see data contract):
            # "Right" if score > 0.5 else "Left".
            name = "Right" if handed_score > 0.5 else "Left"
            handedness.append([_Category(category_name=name, score=handed_score)])

            if self._roi_tracking:
                new_tracked.append({
                    "palm": _palm_from_landmarks(screen),
                    "bbox": tuple(float(v) for v in res[0:4]),
                })

        self._tracked = new_tracked
        return _HandResult(hand_landmarks, handedness, hand_world_landmarks)

    def close(self):
        # Stop the worker thread, then drop the sessions (freed by GC).
        # Present so main.py's `hand_detector.close()` works in both modes.
        self._stop = True
        self._wakeup.set()
        if self._worker is not None:
            self._worker.join(timeout=2.0)
            self._worker = None
        self._palm = None
        self._handpose = None
