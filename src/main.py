import time

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

POSE_MODEL_PATH = "models/pose_landmarker_lite.task"
HAND_MODEL_PATH = "models/hand_landmarker.task"
IMAGE_FORMAT = mp.ImageFormat.SRGB
SELECTED_CAMERA = 0
start_time = time.monotonic()

# Latest async results, written from the MediaPipe callback threads.
latest_pose_result = None
latest_hand_result = None


def on_pose_result(result, output_image, timestamp_ms):
    global latest_pose_result
    latest_pose_result = result


def on_hand_result(result, output_image, timestamp_ms):
    global latest_hand_result
    latest_hand_result = result


def main():
    """
    Capture webcam video and overlay a real-time pose + hand skeleton using
    MediaPipe in LIVE_STREAM (async) mode.  Press 'q' to quit.
    """
    # Model configuration
    pose_base_options = python.BaseOptions(model_asset_path=POSE_MODEL_PATH)
    hand_base_options = python.BaseOptions(model_asset_path=HAND_MODEL_PATH)
    running_mode = vision.RunningMode.LIVE_STREAM

    # Detection thresholds
    num_poses = 1
    min_pose_detection_confidence = 0.5
    min_pose_presence_confidence = 0.5
    min_pose_tracking_confidence = 0.5

    num_hands = 2
    min_hand_detection_confidence = 0.5
    min_hand_presence_confidence = 0.5
    min_hand_tracking_confidence = 0.5

    hand_options = vision.HandLandmarkerOptions(
        base_options=hand_base_options,
        running_mode=running_mode,
        num_hands=num_hands,
        min_hand_detection_confidence=min_hand_detection_confidence,
        min_hand_presence_confidence=min_hand_presence_confidence,
        min_tracking_confidence=min_hand_tracking_confidence,
        result_callback=on_hand_result,
    )

    pose_options = vision.PoseLandmarkerOptions(
        base_options=pose_base_options,
        running_mode=running_mode,
        num_poses=num_poses,
        min_pose_detection_confidence=min_pose_detection_confidence,
        min_pose_presence_confidence=min_pose_presence_confidence,
        min_tracking_confidence=min_pose_tracking_confidence,
        result_callback=on_pose_result,
    )

    pose_detector = vision.PoseLandmarker.create_from_options(options=pose_options)
    hand_detector = vision.HandLandmarker.create_from_options(options=hand_options)

    camera = cv2.VideoCapture(SELECTED_CAMERA)

    if not camera.isOpened():
        print(f"Cant access to camera #{SELECTED_CAMERA}")
        return

    pose_connections = vision.PoseLandmarksConnections.POSE_LANDMARKS
    hand_connections = vision.HandLandmarksConnections.HAND_CONNECTIONS

    while True:
        success, frame = camera.read()
        flip_frame = cv2.flip(src=frame, flipCode=1)
        mp_image = toMpImage(frame=flip_frame)

        timestamps_ms = int((time.monotonic() - start_time) * 1000)

        # Non-blocking: results arrive later via the callbacks above.
        pose_detector.detect_async(image=mp_image, timestamp_ms=timestamps_ms)
        hand_detector.detect_async(image=mp_image, timestamp_ms=timestamps_ms)

        # Snapshot the latest results so a callback firing mid-frame
        # doesn't swap them out while we're drawing.
        pose_result = latest_pose_result
        hand_result = latest_hand_result

        if pose_result is not None:
            draw(landMarks=pose_result.pose_landmarks, frame=flip_frame,
                 landMarkConections=pose_connections, individiual_detection_index=0)

        if hand_result is not None:
            for i in range(len(hand_result.hand_landmarks)):
                draw(landMarks=hand_result.hand_landmarks, frame=flip_frame,
                     landMarkConections=hand_connections, individiual_detection_index=i)

        cv2.imshow("Camera", flip_frame)

        key = cv2.waitKey(1) & 0xFF

        if key == ord("q"):
            break

    camera.release()
    pose_detector.close()
    hand_detector.close()
    cv2.destroyAllWindows()


def draw(landMarks, frame, landMarkConections, individiual_detection_index):

    if landMarks:
        h, w, _ = frame.shape
        individual_detection = landMarks[individiual_detection_index]

        for landmark in individual_detection:
            if landmark.visibility != None:
                if landmark.visibility < 0.5:
                    continue
            x = int(landmark.x * w)
            y = int(landmark.y * h)
            cv2.circle(
                img=frame,
                center=(x, y),
                radius=4,
                color=(0, 255, 0),
                thickness=-1,
            )
        for conection in landMarkConections:
            start = individual_detection[conection.start]
            end = individual_detection[conection.end]
            if start.visibility != None or end.visibility != None:
                if start.visibility < 0.5 or end.visibility < 0.5:
                    continue

            start_x = int(start.x * w)
            start_y = int(start.y * h)

            end_x = int(end.x * w)
            end_y = int(end.y * h)

            cv2.line(frame, (start_x, start_y), (end_x, end_y), (255, 0, 0), 2)

    else:
        print("not Detected")


def toMpImage(frame):

    rgb_frame = cv2.cvtColor(src=frame, code=cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=IMAGE_FORMAT, data=rgb_frame)
    return mp_image


if __name__ == "__main__":
    main()
