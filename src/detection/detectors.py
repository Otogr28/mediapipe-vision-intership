import time

from mediapipe.tasks import python
from mediapipe.tasks.python import vision

from config import (HALL_INFERENCE, HAND_MODEL_PATH,
                    MIN_HAND_DETECTION_CONFIDENCE,
                    MIN_HAND_PRESENCE_CONFIDENCE, MIN_HAND_TRACKING_CONFIDENCE,
                    MIN_POSE_DETECTION_CONFIDENCE,
                    MIN_POSE_PRESENCE_CONFIDENCE, MIN_POSE_TRACKING_CONFIDENCE,
                    NUM_HANDS, NUM_POSES, POSE_INFERENCE, POSE_MODEL_PATH)

latest_pose_result = None
# (result, receive time.monotonic()) — like the hand packet, so the pose
# smoother can extrapolate by the result's true age.
latest_pose_packet = (None, None)
latest_hand_result = None
# (result, receive time.monotonic(), submitted timestamp_ms) published as ONE
# tuple assignment so a reader can never pair a new result with an old time —
# the callbacks run on MediaPipe's (or the GPU backend's) worker thread, not
# the render loop. The submitted timestamp rides along because `hand_view.py`
# has to remap the landmarks with the WINDOW that produced them, and by the
# time a result arrives the current window has usually moved on.
latest_hand_packet = (None, None, None)

# EMA of the interval between hand-result callbacks -> detector FPS.
_HAND_DT_EMA_ALPHA = 0.1
_hand_dt_ema = 0.0
_hand_last_t = None
# Same, for pose — so the debug HUD can show the real body-pose rate (CPU
# MediaPipe ~13 fps vs the GPU backend) instead of us guessing it.
_pose_dt_ema = 0.0
_pose_last_t = None


def on_pose_result(result, output_image, timestamp_ms):
    global latest_pose_result, latest_pose_packet, _pose_dt_ema, _pose_last_t
    now = time.monotonic()
    latest_pose_result = result
    latest_pose_packet = (result, now)
    if _pose_last_t is not None:
        dt = now - _pose_last_t
        _pose_dt_ema = (dt if _pose_dt_ema == 0.0 else
                        (1.0 - _HAND_DT_EMA_ALPHA) * _pose_dt_ema
                        + _HAND_DT_EMA_ALPHA * dt)
    _pose_last_t = now


def on_hand_result(result, output_image, timestamp_ms):
    global latest_hand_result, latest_hand_packet, _hand_dt_ema, _hand_last_t
    now = time.monotonic()
    latest_hand_result = result
    latest_hand_packet = (result, now, timestamp_ms)
    if _hand_last_t is not None:
        dt = now - _hand_last_t
        _hand_dt_ema = (dt if _hand_dt_ema == 0.0 else
                        (1.0 - _HAND_DT_EMA_ALPHA) * _hand_dt_ema
                        + _HAND_DT_EMA_ALPHA * dt)
    _hand_last_t = now


def hand_fps():
    """Smoothed hand-detector callback rate (Hz); 0.0 until two results."""
    return 1.0 / _hand_dt_ema if _hand_dt_ema > 0.0 else 0.0


def pose_fps():
    """Smoothed pose-detector callback rate (Hz); 0.0 until two results."""
    return 1.0 / _pose_dt_ema if _pose_dt_ema > 0.0 else 0.0


def build_pose_detector():
    """Build the pose detector for the configured backend.

    HALL_POSE_INFERENCE == "gpu" returns the onnxruntime two-stage BlazePose
    detector (GpuPoseDetector, CUDA/TensorRT-capable); anything else (default
    "mediapipe") returns MediaPipe's PoseLandmarker. Both expose
    ``detect_async(image, timestamp_ms)`` and ``close()`` and publish results
    via ``on_pose_result`` into ``latest_pose_packet``, so ``main.py`` is
    identical for both.
    """
    if POSE_INFERENCE == "gpu":
        # Lazy import: keeps the onnxruntime dependency off the default path.
        from detection.gpu_pose import GpuPoseDetector
        return GpuPoseDetector(result_callback=on_pose_result)

    base_options = python.BaseOptions(model_asset_path=POSE_MODEL_PATH)
    options = vision.PoseLandmarkerOptions(
        base_options=base_options,
        running_mode=vision.RunningMode.LIVE_STREAM,
        num_poses=NUM_POSES,
        min_pose_detection_confidence=MIN_POSE_DETECTION_CONFIDENCE,
        min_pose_presence_confidence=MIN_POSE_PRESENCE_CONFIDENCE,
        min_tracking_confidence=MIN_POSE_TRACKING_CONFIDENCE,
        result_callback=on_pose_result,
    )
    return vision.PoseLandmarker.create_from_options(options=options)


def build_hand_detector():
    """Build the hand detector for the configured backend.

    HALL_INFERENCE == "gpu" returns the onnxruntime two-stage detector
    (GpuHandDetector); anything else (default "mediapipe") returns MediaPipe's
    HandLandmarker. Both expose ``detect_async(image, timestamp_ms)`` and
    ``close()`` and publish results via ``on_hand_result`` into
    ``latest_hand_result``, so ``main.py`` is identical for both.
    """
    if HALL_INFERENCE == "gpu":
        # Lazy import: keeps the onnxruntime dependency (pulled in by this
        # module) off the default MediaPipe path.
        from detection.gpu_hands import GpuHandDetector
        return GpuHandDetector(result_callback=on_hand_result)

    base_options = python.BaseOptions(model_asset_path=HAND_MODEL_PATH)
    options = vision.HandLandmarkerOptions(
        base_options=base_options,
        running_mode=vision.RunningMode.LIVE_STREAM,
        num_hands=NUM_HANDS,
        min_hand_detection_confidence=MIN_HAND_DETECTION_CONFIDENCE,
        min_hand_presence_confidence=MIN_HAND_PRESENCE_CONFIDENCE,
        min_tracking_confidence=MIN_HAND_TRACKING_CONFIDENCE,
        result_callback=on_hand_result,
    )
    return vision.HandLandmarker.create_from_options(options=options)
