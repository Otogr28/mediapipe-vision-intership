import time
import traceback

import cv2
from mediapipe.tasks.python import vision

from detection import detectors
from config import SELECTED_CAMERA, WINDOW_WIDTH, WINDOW_HEIGHT
from detection.detectors import build_pose_detector, build_hand_detector
from rendering.drawing import toMpImage, draw_landmarks, draw_connections, draw_line
from ui.manager import UIManager
from output import make_sink
from capture import FreshestFrame

start_time = time.monotonic()
last_timestamp_ms = -1


def _camera_source(value):
    """Resolve the configured camera source: a device index ('0' -> 0) or a
    stream URL / device path, which is passed to OpenCV unchanged."""
    return int(value) if str(value).isdigit() else value


def main():
    """
    Capture video and overlay a real-time pose + hand skeleton using MediaPipe
    in LIVE_STREAM (async) mode.

    The source (SELECTED_CAMERA / HALL_CAMERA) is either a local device index
    or a stream URL — e.g. an MJPEG feed from a laptop — so this node can infer
    on a remote camera. The annotated output goes to the sink chosen by config
    (HALL_OUTPUT): an on-screen window ('q' to quit) or a headless MJPEG server
    for a remote browser. Ctrl-C also quits.
    """
    pose_detector = build_pose_detector()
    hand_detector = build_hand_detector()

    source = _camera_source(SELECTED_CAMERA)
    if isinstance(source, int):
        # A local webcam: force the V4L2 backend. OpenCV's default backend on
        # the Jetson is GStreamer, which IGNORES the FOURCC/FPS requests and
        # opens the C920 in a raw full-resolution mode that delivers only ~2
        # fps (a ~500 ms blocking read) — that, not inference, was the app's
        # real bottleneck. V4L2 + MJPG honours the requests and gives 30 fps.
        # MJPG must be requested before the resolution: the C920 only offers
        # 1920x1080 in MJPG; its raw YUYV modes top out at 640x480.
        camera = cv2.VideoCapture(source, cv2.CAP_V4L2)
        camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, WINDOW_WIDTH)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, WINDOW_HEIGHT)
        camera.set(cv2.CAP_PROP_FPS, 30)
        # Ask the driver to keep the shallowest possible queue so read()
        # returns the *freshest* frame. When the loop runs slower than the
        # camera's frame rate, the driver otherwise buffers the backlog and
        # read() hands back progressively older frames — that growing lag is
        # the "camera delay". (V4L2 may ignore this; the real cure is dropping
        # stale frames — see the note in the loop below.)
        camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    else:
        # A network stream (MJPEG URL) is decoded as-is by the default backend.
        camera = cv2.VideoCapture(source)
    if not camera.isOpened():
        print(f"Cant access to camera {source!r}")
        return

    # Read one frame to learn the true frame size — a network source reports 0
    # from CAP_PROP_* until the first frame is decoded — then size the UI to it.
    ok, probe = camera.read()
    if not ok or probe is None:
        print("Camera opened but returned no frames")
        camera.release()
        return
    frame_h, frame_w = probe.shape[:2]

    # Wrap the capture so the loop always gets the newest frame. This is the
    # real cure for the "camera delay": a background thread drains the capture
    # continuously and keeps only the latest frame, so when the render loop is
    # slower than the camera the stale frames are dropped instead of piling up
    # in the driver queue. Latency stays ~1 frame regardless of loop speed.
    camera = FreshestFrame(camera)

    ui = UIManager(frame_w, frame_h)
    sink = make_sink(frame_w, frame_h)

    pose_connections = vision.PoseLandmarksConnections.POSE_LANDMARKS
    hand_connections = vision.HandLandmarksConnections.HAND_CONNECTIONS

    global last_timestamp_ms
    last_error = None
    try:
        while True:
            try:
                success, frame = camera.read()
                if not success or frame is None:
                    # A network source can momentarily starve; keep polling.
                    continue
                flip_frame = cv2.flip(src=frame, flipCode=1)
                mp_image = toMpImage(frame=flip_frame)

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

                sink.present(flip_frame)
                if sink.should_quit():
                    break
            except Exception:
                # A single bad frame, draw, or GPU call must not take down a
                # long-running headless appliance. Log each distinct error
                # once (not 30x/s) and keep serving the stream.
                tb = traceback.format_exc()
                if tb != last_error:
                    print("=== frame error (continuing) ===\n" + tb, flush=True)
                    last_error = tb
                continue
    except KeyboardInterrupt:
        pass
    finally:
        camera.release()
        pose_detector.close()
        hand_detector.close()
        sink.close()


if __name__ == "__main__":
    main()
