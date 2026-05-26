import cv2
import mediapipe as mp

from config import IMAGE_FORMAT


def toMpImage(frame):
    rgb_frame = cv2.cvtColor(src=frame, code=cv2.COLOR_BGR2RGB)
    return mp.Image(image_format=IMAGE_FORMAT, data=rgb_frame)


def draw_landmarks(individual_detection, frame):
    h, w, _ = frame.shape
    for landmark in individual_detection:
        if landmark.visibility is not None:
            if landmark.visibility < 0.5:
                continue
        x = int(landmark.x * w)
        y = int(landmark.y * h)
        cv2.circle(img=frame, center=(x, y), radius=4, color=(0, 255, 0), thickness=-1)


def draw_line(individual_detection, frame, startI, endI):
    h, w, _ = frame.shape
    startP = individual_detection[startI]
    endP = individual_detection[endI]

    if startP.visibility is not None and endP.visibility is not None:
        if startP.visibility < 0.5 and endP.visibility < 0.5:
            return
    xs = int(startP.x * w)
    ys = int(startP.y * h)
    xe = int(endP.x * w)
    ye = int(endP.y * h)

    cv2.line(frame, (xs, ys), (xe, ye), (0, 255, 0), 3)

    dist = ((xe - xs) ** 2 + (ye - ys) ** 2) ** 0.5
    mid_x = (xs + xe) // 2
    mid_y = (ys + ye) // 2
    label = f"{dist:.1f}px"
    cv2.putText(frame, label, (mid_x, mid_y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)


def draw_connections(individual_detection, frame, connections):
    h, w, _ = frame.shape
    for connection in connections:
        start = individual_detection[connection.start]
        end = individual_detection[connection.end]
        if start.visibility is not None or end.visibility is not None:
            if start.visibility < 0.5 or end.visibility < 0.5:
                continue
        start_x = int(start.x * w)
        start_y = int(start.y * h)
        end_x = int(end.x * w)
        end_y = int(end.y * h)
        cv2.line(frame, (start_x, start_y), (end_x, end_y), (255, 0, 0), 2)
