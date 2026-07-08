"""GPU/ONNX body-pose backend.

An alternative to MediaPipe's PoseLandmarker that runs the same two-stage
BlazePose pipeline (person detection -> pose landmark) through onnxruntime, so
it can use the CUDA / TensorRT execution provider on the Jetson instead of the
CPU MediaPipe path (which runs ~13 fps and lags the GPU hands). Selected by
``HALL_POSE_INFERENCE=gpu`` in config; the MediaPipe path stays the default.

The detector emits a result object drop-in compatible with what the app
consumes from MediaPipe's PoseLandmarkerResult:

* ``result.pose_landmarks`` -> list (one entry per detected pose) of 33 landmark
  objects with ``.x`` / ``.y`` normalized to [0, 1], ``.z`` (hip-relative), and
  ``.visibility`` (0..1). ``main.py`` reads ``pose_landmarks[0]``.
* ``result.pose_world_landmarks`` -> parallel list of 33 metric landmarks
  (meters, origin at the hips) — the smoother/rig read ``pose_world_landmarks[0]``.

When no pose is detected the result has empty (not None) lists, matching
MediaPipe. Inference runs on a background worker thread like MediaPipe's
LIVE_STREAM mode, so ``detect_async`` never blocks the camera/draw loop.

onnxruntime is imported lazily (inside the vendored ``_zoo`` classes), so the
default MediaPipe path does not require onnxruntime to be installed.
"""

import threading
import traceback

import numpy as np

from config import (MIN_POSE_DETECTION_CONFIDENCE,
                    MIN_POSE_PRESENCE_CONFIDENCE, ONNX_PROVIDERS,
                    POSE_DET_ONNX, POSE_LM_ONNX)


class _PoseResult:
    """Stand-in for mediapipe's PoseLandmarkerResult.

    Only the two fields the app reads are populated: ``pose_landmarks`` and
    ``pose_world_landmarks`` (parallel lists, one entry per pose)."""

    __slots__ = ("pose_landmarks", "pose_world_landmarks", "segmentation_masks")

    def __init__(self, pose_landmarks, pose_world_landmarks):
        self.pose_landmarks = pose_landmarks
        self.pose_world_landmarks = pose_world_landmarks
        self.segmentation_masks = None


class GpuPoseDetector:
    """Two-stage ONNX pose detector with a MediaPipe-compatible interface.

    Exposes ``detect_async(image, timestamp_ms)`` and ``close()`` so it is a
    drop-in for the MediaPipe PoseLandmarker that ``main.py`` drives. Like
    ``GpuHandDetector``, inference runs on a background worker that always
    processes the most recent submitted frame (dropping any it can't keep up
    with) and hands the result to ``result_callback`` exactly like MediaPipe's
    async callback (which stores it into ``detectors.latest_pose_packet``).
    """

    def __init__(
        self,
        result_callback,
        det_path=POSE_DET_ONNX,
        lm_path=POSE_LM_ONNX,
        providers=None,
        det_score_threshold=MIN_POSE_DETECTION_CONFIDENCE,
        lm_conf_threshold=MIN_POSE_PRESENCE_CONFIDENCE,
    ):
        # Imported here (not at module top) so building this detector is what
        # pulls in onnxruntime + the vendored classes; the MediaPipe default
        # path never touches them.
        from detection._zoo.mp_persondet import MPPersonDet
        from detection._zoo.mp_poselandmark import MPPoseLandmark

        providers = list(providers) if providers is not None else list(ONNX_PROVIDERS)

        self._result_callback = result_callback
        self._det = MPPersonDet(
            det_path,
            scoreThreshold=det_score_threshold,
            providers=providers,
        )
        self._lm = MPPoseLandmark(
            lm_path,
            confThreshold=lm_conf_threshold,
            providers=providers,
        )

        # Background inference worker (same design as GpuHandDetector).
        self._lock = threading.Lock()
        self._pending = None          # (bgr, timestamp_ms)
        self._wakeup = threading.Event()
        self._stop = False
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def detect_async(self, image, timestamp_ms=None):
        """Hand the latest frame to the worker thread (non-blocking).

        ``image`` is a ``mediapipe.Image`` (built by ``toMpImage``), so its
        ``numpy_view()`` is an RGB ndarray. The vendored pipeline expects BGR,
        so convert here (also yielding an owned copy safe to hand across the
        thread) and return immediately.
        """
        import cv2

        bgr = cv2.cvtColor(image.numpy_view(), cv2.COLOR_RGB2BGR)
        with self._lock:
            self._pending = (bgr, timestamp_ms)
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
            bgr, timestamp_ms = job
            try:
                result = self._infer(bgr)
            except Exception:
                # A bad frame must not kill the worker; log and keep serving.
                traceback.print_exc()
                continue
            # Mimic MediaPipe's async callback contract (result, image, timestamp).
            self._result_callback(result, None, timestamp_ms)

    def _infer(self, bgr):
        # TODO: ROI tracking from prev-frame landmarks. v1 runs person detection
        # on the full frame every call; MediaPipe re-derives the ROI from the
        # previous frame's landmarks while a pose is tracked and only re-runs
        # detection on loss — a later optimization that both smooths and speeds
        # the pipeline (mirrors the same TODO in gpu_hands.py).
        dets = self._det.infer(bgr)  # (N, 13): [box(4), kps(8), score(1)]

        pose_landmarks = []
        pose_world_landmarks = []

        if dets is not None and len(dets) > 0:
            # Single pose (NUM_POSES == 1): keep the highest-scoring detection.
            best = dets[int(np.argmax(dets[:, -1]))]
            res = self._lm.infer(bgr, best)
            if res is not None:
                screen, world = res
                pose_landmarks.append(screen)
                pose_world_landmarks.append(world)

        return _PoseResult(pose_landmarks, pose_world_landmarks)

    def close(self):
        # Stop the worker thread, then drop the sessions (freed by GC).
        # Present so main.py's `pose_detector.close()` works in both modes.
        self._stop = True
        self._wakeup.set()
        if self._worker is not None:
            self._worker.join(timeout=2.0)
            self._worker = None
        self._det = None
        self._lm = None
