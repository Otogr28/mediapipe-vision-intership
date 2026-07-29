import time
import traceback

import cv2
from mediapipe.tasks.python import vision

from capture import (FreshestFrame, apply_camera_controls, device_path,
                     resolve_camera_source, restore_auto_exposure)
from config import (CAMERA_CONTROLS, CAMERA_STALL_S, DEBUG_HUD, POSE_ENABLED,
                    POSE_SMOOTHING, PREPROCESS_SPEC, PROC_WIDTH,
                    SELECTED_CAMERA, STATE_FPS, WINDOW_HEIGHT, WINDOW_WIDTH)
from detection import detectors
from detection.detectors import build_hand_detector, build_pose_detector
from detection.pose_smoother import PoseSmoother
from output import make_sink
from preprocess import Preprocessor
from rendering.drawing import draw_connections, draw_landmarks, toMpImage
from ui.manager import UIManager
from web.state import build_state

start_time = time.monotonic()
last_timestamp_ms = -1


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
    # Pose is optional (HALL_POSE, off by default): the UI is fully
    # hand-driven and body inference was the biggest CPU cost on the Jetson.
    # HALL_POSE=1 builds it up front (always on); otherwise it is built
    # LAZILY the first time a feature asks for it (ui.wants_pose(), e.g. the
    # Vtuber puppet) and then only run while that feature is active — so pose
    # costs nothing until the user opts into something that needs a skeleton.
    pose_detector = build_pose_detector() if POSE_ENABLED else None
    hand_detector = build_hand_detector()

    # The index is resolved against the kernel rather than taken on trust: a
    # camera swap renumbers /dev/video*, and a UVC camera's second node is
    # metadata that opens without ever yielding a frame (see capture.py).
    source, kind = resolve_camera_source(SELECTED_CAMERA)
    if kind == "v4l2":
        # A local webcam: force the V4L2 backend. OpenCV's default backend on
        # the Jetson is GStreamer, which IGNORES the FOURCC/FPS requests and
        # opens the camera in a raw full-resolution mode that delivers only ~2
        # fps (a ~500 ms blocking read) — that, not inference, was the app's
        # real bottleneck. V4L2 + MJPG honours the requests and gives 30 fps.
        # MJPG must be requested before the resolution: the C920 only offered
        # 1920x1080 in MJPG (its raw YUYV modes topped out at 640x480), and
        # MJPG is what keeps the USB bandwidth sane on the MX Brio too.
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

    if kind == "v4l2":
        # Exposure/gain/crop, applied only where HALL_CAM_* asked for it. This
        # runs AFTER the open because setting the capture format resets some
        # UVC controls, and it runs HERE rather than from a shell script
        # because the kiosk restarts itself and a camera re-enumeration would
        # otherwise silently drop back to the backlit picture.
        apply_camera_controls(device_path(source), CAMERA_CONTROLS)

    if kind == "v4l2" and CAMERA_CONTROLS.get("auto_exposure") is None:
        # Nobody asked for a manual exposure this run: give the camera its own
        # automatic mode back. A UVC control outlives the process that wrote
        # it, so a previous run that pinned Manual would otherwise leave every
        # later run frozen at that exposure, unable to respond to the room.
        restore_auto_exposure(device_path(source))

    # Read one frame to learn the true frame size — a network source reports 0
    # from CAP_PROP_* until the first frame is decoded — then size the UI to it.
    ok, probe = camera.read()
    if not ok or probe is None:
        print("Camera opened but returned no frames")
        camera.release()
        return
    frame_h, frame_w = probe.shape[:2]

    # What the app WORKS in, which can be smaller than what it CAPTURES: a
    # bigger capture buys the visitor a sharper picture of themselves, and
    # downscaling it once per frame keeps the detectors, the presence test and
    # every pixel constant on the frame size they were tuned at (see
    # config.PROC_WIDTH). The height is derived from the capture's real aspect
    # so the browser's overlay stays lined up with the video it is drawn over.
    proc_w, proc_h = frame_w, frame_h
    if 0 < PROC_WIDTH < frame_w:
        proc_w = PROC_WIDTH
        proc_h = max(2, int(round(frame_h * PROC_WIDTH / frame_w)) // 2 * 2)
    downscale = (proc_w, proc_h) != (frame_w, frame_h)

    # Wrap the capture so the loop always gets the newest frame. This is the
    # real cure for the "camera delay": a background thread drains the capture
    # continuously and keeps only the latest frame, so when the render loop is
    # slower than the camera the stale frames are dropped instead of piling up
    # in the driver queue. Latency stays ~1 frame regardless of loop speed.
    # A local video FILE (not a device index, not a network stream URL) is a
    # testing source: loop it and pace it to its native fps so the app can be
    # driven from a recorded clip. Webcam/stream sources read flat out as before.
    _is_file = kind == "file"
    _file_fps = camera.get(cv2.CAP_PROP_FPS) if _is_file else 0.0
    camera = FreshestFrame(camera, loop=_is_file,
                           fps=_file_fps if _file_fps and _file_fps > 1 else 0.0)

    sink = make_sink(proc_w, proc_h)
    # Web mode is detected by capability, not config: the WebSink takes the
    # per-frame state JSON, the browser renders all UI, and the backend
    # neither draws on the frame nor creates a GL context.
    publish_state = getattr(sink, "publish_state", None)
    ui = UIManager(proc_w, proc_h, gpu_effects=publish_state is None)

    pose_connections = vision.PoseLandmarksConnections.POSE_LANDMARKS
    hand_connections = vision.HandLandmarksConnections.HAND_CONNECTIONS

    # What the hand detector is SHOWN. `preprocess` is the contrast knob, off
    # by default because it measured as no help; see the module for the numbers.
    preprocess = Preprocessor(PREPROCESS_SPEC)
    # Said out loud at startup: this layer is invisible when it works, and when
    # it misbehaves the symptom is "the model stopped finding hands", which is
    # indistinguishable from every other cause unless the log says it was on.
    print("hand detector input: full frame · preprocess %s"
          % preprocess.describe(), flush=True)
    # Same reason: a picture that is sharper than the app's own coordinate
    # space is invisible when it works, and reads as "the overlay drifted"
    # when it does not.
    print("capture %dx%d · app+model %dx%d%s"
          % (frame_w, frame_h, proc_w, proc_h,
             " (downscaled per frame)" if downscale else ""), flush=True)

    global last_timestamp_ms
    last_error = None
    # Set once if the lazy pose-detector build fails, so we don't retry (and
    # skip frames) every tick — the app just stays hand-only in that case.
    pose_build_failed = False
    # One-Euro smoothing + velocity extrapolation for the body pose (see
    # PoseSmoother) — fed on each new pose result, sampled every frame.
    pose_smoother = PoseSmoother()
    last_pose_obj = None
    # Web mode paces the loop to STATE_FPS: without cv2 drawing the loop
    # would spin far faster than the camera delivers frames, re-encoding
    # the same JPEG and re-running inference on duplicate frames for
    # nothing (FreshestFrame.read() never blocks). Window/stream modes
    # keep their historical free-running behaviour.
    frame_interval = 1.0 / STATE_FPS if publish_state is not None else 0.0
    next_frame_t = time.monotonic()
    try:
        while True:
            try:
                if frame_interval:
                    now = time.monotonic()
                    if now < next_frame_t:
                        time.sleep(next_frame_t - now)
                    next_frame_t = max(now, next_frame_t) + frame_interval

                success, frame = camera.read()
                if not success or frame is None:
                    # A network source can momentarily starve; keep polling.
                    continue

                # Appliance self-healing: a wedged camera keeps handing back
                # the SAME frame forever (no error, no new data) — the kiosk
                # would show a frozen picture while everything reads healthy.
                # In web mode, bail out so the supervisor restarts us with a
                # fresh camera handle.
                if (publish_state is not None and CAMERA_STALL_S > 0
                        and camera.frame_age() > CAMERA_STALL_S):
                    print(f"camera stalled ({CAMERA_STALL_S:.0f}s without a "
                          "new frame) — exiting for supervisor restart",
                          flush=True)
                    break
                flip_frame = cv2.flip(src=frame, flipCode=1)

                # From here on `view_frame` is the visitor's picture at
                # capture resolution and `flip_frame` is what the app reasons
                # about. INTER_AREA because this is a downscale and it is the
                # filter that averages the pixels it drops — a hand thins out
                # and loses contrast against the window under INTER_LINEAR,
                # and the hand's readability is the whole problem here.
                view_frame = flip_frame
                if downscale:
                    flip_frame = cv2.resize(flip_frame, (proc_w, proc_h),
                                            interpolation=cv2.INTER_AREA)

                timestamps_ms = max(int((time.monotonic() - start_time) * 1000), last_timestamp_ms + 1)
                last_timestamp_ms = timestamps_ms

                # Run pose only when needed: the HALL_POSE=1 override, or a
                # live feature that asks for it (ui.wants_pose()). Built lazily
                # on first demand — a one-time model-load hitch when the user
                # first enters e.g. Vtuber, then free on exit (we simply stop
                # feeding it; its threads idle). timestamps_ms keeps climbing
                # every frame, so the stream stays monotonic across on/off gaps.
                need_pose = POSE_ENABLED or ui.wants_pose()
                if need_pose and pose_detector is None and not pose_build_failed:
                    try:
                        pose_detector = build_pose_detector()
                        print("pose inference enabled on demand", flush=True)
                    except Exception:
                        pose_build_failed = True
                        print("pose detector build failed; staying hand-only",
                              flush=True)
                if need_pose and pose_detector is not None:
                    pose_detector.detect_async(image=toMpImage(frame=flip_frame),
                                               timestamp_ms=timestamps_ms)
                    pose_result, pose_received_t = detectors.latest_pose_packet
                else:
                    pose_result, pose_received_t = None, None

                hand_detector.detect_async(image=toMpImage(frame=preprocess(flip_frame)),
                                           timestamp_ms=timestamps_ms)

                hand_result, hand_received_t = detectors.latest_hand_packet

                # Smooth the body: feed the One-Euro smoother on each NEW pose
                # result, then sample its filtered + velocity-extrapolated output
                # for THIS frame so the body glides between the ~13 fps results
                # instead of stuttering/lagging (PoseSmoother). No person or pose
                # off -> reset so it eases back in rather than snapping. The 3D
                # world skeleton (meters, hips origin) drives the vtuber rig.
                pose_landmarks = None
                pose_world_landmarks = None
                if need_pose and pose_result is not None and pose_result.pose_landmarks:
                    if pose_result is not last_pose_obj:
                        last_pose_obj = pose_result
                        _w = getattr(pose_result, "pose_world_landmarks", None)
                        pose_smoother.update(pose_result.pose_landmarks[0],
                                             _w[0] if _w else None,
                                             pose_received_t or time.monotonic())
                    if POSE_SMOOTHING:
                        pose_landmarks, pose_world_landmarks = \
                            pose_smoother.sample(time.monotonic())
                    else:
                        pose_landmarks = pose_result.pose_landmarks[0]
                        _w = getattr(pose_result, "pose_world_landmarks", None)
                        pose_world_landmarks = _w[0] if _w else None
                else:
                    pose_smoother.reset()
                    last_pose_obj = None

                # UI first, drawing second. The mirrored frame goes into
                # update() as well — attract mode's presence detector reads
                # motion off it to notice somebody walking up with their
                # hands down, which no landmark model can see — and it has
                # to be the CAMERA image, before any skeleton is painted on
                # top of it.
                ui.update(hand_result, pose_landmarks, hand_received_t,
                          frame=flip_frame)

                # Web mode streams the RAW frame — the browser draws the
                # skeleton and all UI from the published state instead.
                if publish_state is None:
                    if pose_landmarks is not None:
                        draw_landmarks(pose_landmarks, flip_frame)
                        draw_connections(pose_landmarks, flip_frame, pose_connections)
                    if hand_result is not None:
                        for i in range(len(hand_result.hand_landmarks)):
                            draw_landmarks(hand_result.hand_landmarks[i], flip_frame)
                            draw_connections(hand_result.hand_landmarks[i], flip_frame, hand_connections)

                if publish_state is None:
                    ui.draw(flip_frame)
                else:
                    publish_state(build_state(ui, hand_result, pose_landmarks,
                                              pose_world_landmarks))

                # Web mode presents the full-resolution picture (the browser
                # draws the UI over it from the state payload). Window and
                # stream present the frame Python just drew on, which is the
                # proc one — their overlay is in proc coordinates.
                sink.present(view_frame if publish_state is not None
                             else flip_frame)
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
        if pose_detector is not None:
            pose_detector.close()
        hand_detector.close()
        sink.close()


if __name__ == "__main__":
    main()
