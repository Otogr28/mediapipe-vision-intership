import time

import cv2
from mediapipe.tasks.python import vision

from detection import detectors
from config import SELECTED_CAMERA, WINDOW_WIDTH, WINDOW_HEIGHT
from detection.detectors import build_pose_detector, build_hand_detector
from rendering.drawing import toMpImage, draw_landmarks, draw_connections, draw_line
from ui.manager import UIManager

start_time = time.monotonic()
last_timestamp_ms = -1


def main():
    """
    Capture webcam video and overlay a real-time pose + hand skeleton using
    MediaPipe in LIVE_STREAM (async) mode.  Press 'q' to quit.
    """
    pose_detector = build_pose_detector()
    hand_detector = build_hand_detector()

    camera = cv2.VideoCapture(SELECTED_CAMERA)

    if not camera.isOpened():
        print(f"Cant access to camera #{SELECTED_CAMERA}")
        return

    camera.set(cv2.CAP_PROP_FRAME_WIDTH, WINDOW_WIDTH)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, WINDOW_HEIGHT)

    frame_w = int(camera.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_h = int(camera.get(cv2.CAP_PROP_FRAME_HEIGHT))

    ui = UIManager(frame_w, frame_h)

    pose_connections = vision.PoseLandmarksConnections.POSE_LANDMARKS
    hand_connections = vision.HandLandmarksConnections.HAND_CONNECTIONS

    while True:
        success, frame = camera.read()
        flip_frame = cv2.flip(src=frame, flipCode=1)
        mp_image = toMpImage(frame=flip_frame)

        global last_timestamp_ms
        timestamps_ms = max(int((time.monotonic() - start_time) * 1000), last_timestamp_ms + 1)
        last_timestamp_ms = timestamps_ms

        pose_detector.detect_async(image=mp_image, timestamp_ms=timestamps_ms)
        hand_detector.detect_async(image=mp_image, timestamp_ms=timestamps_ms)

        pose_result = detectors.latest_pose_result
        hand_result = detectors.latest_hand_result

        pose_landmarks = None
        if pose_result is not None and pose_result.pose_landmarks:
            pose_landmarks = pose_result.pose_landmarks[0]
            draw_landmarks(pose_landmarks, flip_frame)
            draw_connections(pose_landmarks, flip_frame, pose_connections)

        if hand_result is not None:
            for i in range(len(hand_result.hand_landmarks)):
                draw_landmarks(hand_result.hand_landmarks[i], flip_frame)
                draw_connections(hand_result.hand_landmarks[i], flip_frame, hand_connections)
                draw_line(hand_result.hand_landmarks[i], flip_frame, 4, 8)

        ui.update(hand_result, pose_landmarks)
        ui.draw(flip_frame)

        cv2.imshow("Camera", flip_frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break

    camera.release()
    pose_detector.close()
    hand_detector.close()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
