"""
Captures live video from the default camera, flips it horizontally,
and displays it in a window. Press 'q' to quit.
Uses OpenCV for video capture and MediaPipe (imported for future pose detection).
"""
import cv2
import mediapipe as mp

camera = cv2.VideoCapture(0)
mp_pose = mp.solutions.pose
mp_draw = mp.solutions.drawing_utils

while True:
    success, frame = camera.read()

    if not success:
        print("Camera cant be read")
        break
    frame_flip = cv2.flip(frame, 1)
    cv2.imshow("Camera", frame_flip)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break


camera.release()
cv2.destroyAllWindows()
