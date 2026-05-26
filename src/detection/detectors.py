from mediapipe.tasks import python
from mediapipe.tasks.python import vision

from config import (
    POSE_MODEL_PATH, HAND_MODEL_PATH,
    NUM_POSES, MIN_POSE_DETECTION_CONFIDENCE, MIN_POSE_PRESENCE_CONFIDENCE, MIN_POSE_TRACKING_CONFIDENCE,
    NUM_HANDS, MIN_HAND_DETECTION_CONFIDENCE, MIN_HAND_PRESENCE_CONFIDENCE, MIN_HAND_TRACKING_CONFIDENCE,
)

latest_pose_result = None
latest_hand_result = None


def on_pose_result(result, output_image, timestamp_ms):
    global latest_pose_result
    latest_pose_result = result


def on_hand_result(result, output_image, timestamp_ms):
    global latest_hand_result
    latest_hand_result = result


def build_pose_detector():
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
