import time

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

MODEL_PATH = "models/pose_landmarker_lite.task"
CONNECTIONS = [
    (11, 13),  # left shoulder -> left elbow
    (13, 15),  # left elbow -> left wrist

    (12, 14),  # right shoulder -> right elbow
    (14, 16),  # right elbow -> right wrist

    (11, 12),  # shoulders
    (23, 24),  # hips

    (11, 23),  # left shoulder -> left hip
    (12, 24),  # right shoulder -> right hip

    (23, 25),  # left hip -> left knee
    (25, 27),  # left knee -> left ankle

    (24, 26),  # right hip -> right knee
    (26, 28),  # right knee -> right ankle
]
SELECTED_CAMERA = 0
start_time = time.monotonic()


def main():
    """
    Capture webcam video and overlay a real-time pose skeleton using MediaPipe.

    Opens the camera selected by SELECTED_CAMERA, runs the lightweight
    PoseLandmarker model in VIDEO mode on each frame, and draws joint circles
    and limb lines for the first detected person.  Press 'q' to quit.
    """
    # Model configuration
    base_options = python.BaseOptions(model_asset_path=MODEL_PATH)
    running_mode = vision.RunningMode.VIDEO

    # Detection thresholds
    num_poses = 1
    min_pose_detection_confidence = 0.5
    min_pose_presence_confidence = 0.5
    min_tracking_confidence = 0.5

    # Image format
    image_format = mp.ImageFormat.SRGB

    options = vision.PoseLandmarkerOptions(
        base_options=base_options,
        running_mode=running_mode,
        num_poses=num_poses,
        min_pose_detection_confidence=min_pose_detection_confidence,
        min_pose_presence_confidence=min_pose_presence_confidence,
        min_tracking_confidence=min_tracking_confidence,
    )

    detector = vision.PoseLandmarker.create_from_options(options=options)

    camera = cv2.VideoCapture(SELECTED_CAMERA)

    if not camera.isOpened():
        print(f"Cant access to camera #{SELECTED_CAMERA}")
        return

    while True:
        success, frame = camera.read()
        flip_frame = cv2.flip(src=frame, flipCode=1)
        rgb_frame = cv2.cvtColor(src=flip_frame, code=cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=image_format, data=rgb_frame)

        timestamps_ms = int((time.monotonic() - start_time) * 1000)

        result = detector.detect_for_video(mp_image, timestamps_ms)

        pose_landmarks = result.pose_landmarks


        if pose_landmarks:
            h,w,_ = flip_frame.shape

            person = pose_landmarks[0]
            
            for landmark in person:
                if landmark.visibility < 0.5:
                    continue
                x = int(landmark.x * w)
                y = int(landmark.y *h)
                cv2.circle(img=flip_frame,center=(x,y),radius=4,color=(0,255,0),thickness=-1)
            for start_idx, end_idx in CONNECTIONS:
                start = person[start_idx]
                end = person[end_idx]
                if start.visibility < 0.5 or end.visibility < 0.5:
                    continue

                start_x = int(start.x * w)
                start_y = int(start.y * h)

                end_x = int(end.x * w)
                end_y = int(end.y * h)

                cv2.line(flip_frame, (start_x, start_y), (end_x, end_y), (255, 0, 0), 2)
 
        else:
            print("not Detected")

        

        cv2.imshow("Camera", flip_frame)

        key = cv2.waitKey(1) & 0xFF

        if key == ord("q"):
            break

    camera.release()
    detector.close()
    v2.destroyAllWindows()


if __name__ == "__main__":
    main()

