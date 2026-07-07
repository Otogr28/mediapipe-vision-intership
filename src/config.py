import os

import mediapipe as mp

POSE_MODEL_PATH = "models/pose_landmarker_lite.task"
HAND_MODEL_PATH = "models/hand_landmarker.task"
IMAGE_FORMAT = mp.ImageFormat.SRGB

# Inference backend for the HAND pipeline (HALL_INFERENCE):
#   "mediapipe" — default; MediaPipe HandLandmarker (.task), CPU on the Jetson.
#   "gpu"       — onnxruntime palm-detection + handpose, able to use the CUDA
#                 execution provider on the Jetson (CPU fallback elsewhere).
# POSE always stays on MediaPipe (hybrid) for now — only HANDS switch backends.
HALL_INFERENCE = os.environ.get("HALL_INFERENCE", "mediapipe")

# ONNX models for the "gpu" hand backend. Paths are relative to the repo root
# (the app runs from there, matching the .task paths above). Sourced from the
# OpenCV Model Zoo (opencv/opencv_zoo, Apache-2.0).
PALM_ONNX = os.environ.get("HALL_PALM_ONNX", "models/gpu/palm_detection_mediapipe_2023feb.onnx")
HAND_ONNX = os.environ.get("HALL_HAND_ONNX", "models/gpu/handpose_estimation_mediapipe_2023feb.onnx")

# onnxruntime execution providers, in priority order: CUDA first so the Jetson
# uses the GPU, CPU fallback so the same code runs on a laptop without CUDA.
# Override (e.g. to force CPU, or to add TensorRT) with HALL_ONNX_PROVIDERS,
# comma-separated. On the Jetson, hallrun puts TensorrtExecutionProvider first
# (measured ~2.9x faster than CUDA on the hand nets in FP16).
_ONNX_PROVIDER_NAMES = [
    p.strip() for p in os.environ.get(
        "HALL_ONNX_PROVIDERS", "CUDAExecutionProvider,CPUExecutionProvider"
    ).split(",") if p.strip()
]

# Where TensorRT caches compiled engines. Building an engine is slow (palm ~17s,
# handpose ~100s on the Orin) but only happens ONCE per (model, GPU, TRT version,
# input shape): the cache is reused on every later launch, so only the first run
# after a deploy pays it. Lives at the repo root next to models/ (gitignored).
TRT_ENGINE_CACHE = os.environ.get(
    "HALL_TRT_CACHE",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".trt_cache"),
)


def _provider_with_options(name):
    """Attach provider options to TensorRT (engine cache + FP16); pass any other
    provider through as a bare name. onnxruntime accepts a providers list that
    mixes plain names and ``(name, options_dict)`` tuples."""
    if name == "TensorrtExecutionProvider":
        return (name, {
            "trt_engine_cache_enable": True,
            "trt_engine_cache_path": TRT_ENGINE_CACHE,
            "trt_fp16_enable": True,
        })
    return name


ONNX_PROVIDERS = [_provider_with_options(n) for n in _ONNX_PROVIDER_NAMES]

# Camera source. Either a local device index ("0") or a stream URL — e.g. an
# MJPEG feed from another machine ("http://<ip>:8091/stream.mjpg") so this node
# can infer on a *remote* camera (the Jetson pulling a laptop's webcam). Set
# with the HALL_CAMERA env var; defaults to the first local device.
SELECTED_CAMERA = os.environ.get("HALL_CAMERA", "0")

# Where the annotated output goes (HALL_OUTPUT):
#   "window" — an on-screen cv2 window (needs a display); press 'q' to quit.
#   "stream" — a headless MJPEG HTTP server, viewable in a remote browser.
#              Used on the Jetson when driving it from a laptop (no monitor).
#   "web"    — the browser frontend: the same HTTP server additionally serves
#              the built React app (web/dist), streams the RAW camera frame
#              (no cv2 drawing — the browser renders all UI) and pushes the
#              per-frame UI/gesture state as JSON over an SSE endpoint.
OUTPUT_MODE = os.environ.get("HALL_OUTPUT", "window")
# MJPEG server settings for OUTPUT_MODE in ("stream", "web").
# Web mode defaults the bind to 0.0.0.0 instead of the Tailscale IP: the
# Jetson kiosk browser connects to http://localhost:8092/, which an
# auto-resolved Tailscale bind would refuse (Tailscale access still works
# on 0.0.0.0 — it binds every interface).
STREAM_BIND = os.environ.get(
    "HALL_STREAM_BIND", "0.0.0.0" if OUTPUT_MODE == "web" else "auto")
STREAM_PORT = int(os.environ.get("HALL_STREAM_PORT", "8092"))
STREAM_QUALITY = int(os.environ.get("HALL_STREAM_QUALITY", "80"))  # JPEG 1..100
# Web mode: where the built frontend lives (vite build -> web/dist) and how
# often the /state SSE endpoint pushes a fresh snapshot to each client.
WEB_DIST_DIR = os.environ.get(
    "HALL_WEB_DIST",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "web", "dist"),
)
STATE_FPS = int(os.environ.get("HALL_STATE_FPS", "30"))

# Debug overlay (HALL_DEBUG=1): draws the live pinch pipeline on the frame —
# per-hand ratio vs thresholds, machine state, pinch progress, detection
# result age and detector/render FPS. For tuning; off by default.
DEBUG_HUD = os.environ.get("HALL_DEBUG", "0") == "1"

# Requested capture resolution for the webcam. The actual frame size is read
# back after `cv2.VideoCapture.set(...)` because some drivers silently snap
# to the nearest supported mode. The cv2 display window inherits this size.
# Overridable per deployment (HALL_CAPTURE_W/H): inference cost does NOT
# depend on this (models resize internally), but JPEG encode/decode, the
# BGR->RGB copy and the browser's canvas work all scale with it — the
# Jetson kiosk runs 1280x720 (set in hallkiosk) to keep the board from
# saturating; the laptop default stays 1080p.
WINDOW_WIDTH = int(os.environ.get("HALL_CAPTURE_W", "1920"))
WINDOW_HEIGHT = int(os.environ.get("HALL_CAPTURE_H", "1080"))

NUM_POSES = 1
MIN_POSE_DETECTION_CONFIDENCE = 0.5
MIN_POSE_PRESENCE_CONFIDENCE = 0.5
MIN_POSE_TRACKING_CONFIDENCE = 0.5

NUM_HANDS = 2
MIN_HAND_DETECTION_CONFIDENCE = 0.5
MIN_HAND_PRESENCE_CONFIDENCE = 0.5
MIN_HAND_TRACKING_CONFIDENCE = 0.5

# Gesture detection (see detection/gestures.py for the full pipeline).
# The thumb-index distance is normalized by the HAND's own size (knuckle
# span |5-17| vs 0.75x palm length |0-9|, whichever is larger). Those
# segments do not move when the fingers close, so a fist cannot collapse
# the reference; the ratio tracks camera distance automatically; and unlike
# the old shoulder-width scale, the pinch works even when the shoulders /
# pose are not visible.
#
# Ultraleap-style hysteresis: the pinch *closes* below PINCH_CLOSE_RATIO
# and only *reopens* above the looser PINCH_RELEASE_RATIO, so jitter at
# the threshold cannot flicker the state. In knuckle-span units, 0.45 is
# roughly "tips within ~3 cm", 0.90 "tips ~6 cm apart".
PINCH_CLOSE_RATIO = 0.45
PINCH_RELEASE_RATIO = 0.90

# Debounce: consecutive agreeing frames required before the state flips.
# Hand tracking gives brief false negatives exactly while the user pinches
# and moves at once, so releasing demands more evidence than closing.
PINCH_DEBOUNCE_CLOSE_FRAMES = 2
PINCH_DEBOUNCE_RELEASE_FRAMES = 4

# Keep a lost hand's pinch state warm for this long (s): a short tracking
# dropout resumes mid-hold instead of cold-starting the state machine.
PINCH_TRACK_GRACE_S = 0.5

# One-Euro filter (Casiez et al., CHI 2012) — adaptive low-pass: strong
# smoothing at rest (kills jitter), light while moving fast (no lag).
# min_cutoff in Hz; beta grows the cutoff per unit of signal speed.
PINCH_CURSOR_MIN_CUTOFF = 1.5   # cursor midpoint (px)
PINCH_CURSOR_BETA = 0.01
PINCH_RATIO_MIN_CUTOFF = 2.0    # pinch ratio (lighter, keeps clicks snappy)
PINCH_RATIO_BETA = 0.5

# Cursor anchor: the THUMB TIP (landmark 4, hard-wired in gestures.py).
# The thumb is the stable side of a thumb-index pinch — the index does
# most of the closing travel — so the cursor tracks the finger the user
# aims with and stays nearly still through the close. Buttons hit-test
# the press-latched cursor, so residual thumb travel can't slide a click.

# 2D cursor offset in the THUMB's own frame (origin: the thumb tip).
# Both axes are fractions of the visible thumb segment (MCP 2 -> tip 4),
# so they scale with hand size and follow hand rotation automatically:
#   X — along the thumb ray. 0 = at the tip; positive floats the cursor
#       past the tip (0.2 ~ a fingertip ahead), negative pulls it back
#       toward the knuckle.
#   Y — perpendicular to the ray. Positive always pushes toward the
#       INDEX side of the thumb (the sign is resolved per hand, so
#       Left/Right mirror correctly); negative toward the outer edge.
# Keep both small: the thumb ray rotates a little while the fingers
# close, so large offsets reintroduce cursor motion during the pinch.
PINCH_CURSOR_THUMB_OFFSET_X = 0.0
PINCH_CURSOR_THUMB_OFFSET_Y = 0.5

# Pinch counter-movement compensation (0..1). As the fingers close, the
# thumb itself travels toward the index and drags a thumb-anchored
# cursor with it. The cursor point is expressed in a rigid hand frame
# (wrist 0 -> index MCP 5 — segments the fingers cannot move); while the
# hand is open its coordinates in that frame are remembered, and as the
# pinch PROGRESSES the cursor is pulled back toward the remembered point
# — a counter-movement that cancels the thumb's own close travel while
# still following real hand motion (translation, rotation, zoom).
# 1.0 = full compensation (cursor holds still through the close),
# 0.0 = off (cursor rides the raw thumb tip).
PINCH_CURSOR_COMPENSATE = 1.0

# Latency compensation: the cursor is extrapolated forward by its One-Euro
# velocity times the detection result's age, capped here (s). Simple linear
# extrapolation — at short horizons it beats Kalman on jitter.
PINCH_EXTRAP_MAX_S = 0.10

# 3D pinch distance: weight on the landmark z difference (wrist-relative,
# ~x-normalized units, scaled by frame width) mixed into the thumb-index
# distance. Guards against phantom closes when hand rotation aligns the
# fingertips along the camera axis. 0.0 = pure 2D distance (old behavior).
PINCH_Z_WEIGHT = 0.5

# Buttons.
BUTTON_COOLDOWN_FRAMES = 8     # frames before a button can fire again; the
                               # pinch edge-trigger + release debounce is the
                               # real double-fire guard, this only absorbs
                               # tracking glitches
BUTTON_STICKY_PAD_FRAC = 0.15  # sticky targets: while hovered, the hit rect
                               # inflates by this fraction of the button
                               # HEIGHT per side. Height (not width) keeps
                               # the inflation under every button gap — keep
                               # layout gaps > 0.15 * button height.

# Black Hole interactable.
# `BH_EINSTEIN_RADIUS_PX` is the screen-space Einstein radius used by the
# Schwarzschild thin-lens shader. The lensed source radius is computed as
# `r_src = r - E^2/r`; pixels inside `0.5 * E` are rendered as the event-
# horizon shadow, pixels where `r_src <= 0` are captured (also black).
# Increase to make the BH visually heavier; decrease for subtler lensing.
BH_EINSTEIN_RADIUS_PX = 80

# Max distance from pinch midpoint to BH centre to initiate a drag. Matches
# the sphere's GRAB_RADIUS so the interaction model stays consistent.
BH_GRAB_RADIUS = 100

# Initial spawn position as a fraction of frame size (0..1 each axis).
BH_DEFAULT_POS_FACTOR = (0.5, 0.5)

# Accretion disk. Inner/outer radii are expressed as multiples of the
# Einstein radius so the disk scales sensibly when `BH_EINSTEIN_RADIUS_PX`
# is tuned per deployment. `1.5 * E` is roughly the innermost stable
# circular orbit (ISCO) in our screen-space units; `4.0 * E` gives the
# disk visible breadth without dominating the frame.
BH_DISK_INNER_FACTOR = 1.5
BH_DISK_OUTER_FACTOR = 4.0
# Disk tilt in radians: 0 = face-on (boring circular annulus), pi/2 =
# edge-on (a line). ~1.2 rad (~69 deg) is the "Interstellar" angle that
# shows both the front of the disk and the lensed back wrapping over
# the top of the BH.
BH_DISK_TILT_RAD = 1.2
# Overall disk emission multiplier. 0 disables the disk visually
# (useful for a "lensing only" debug view).
BH_DISK_BRIGHTNESS = 1.0
# Angular speed at the disk's inner edge (rad/s). Outer rings rotate
# slower according to Kepler's third law (omega ~ r^(-3/2)), so this
# value only controls the *inner* rim's tangential speed; the disk's
# overall "rotational feel" scales with it. Set to 0 to freeze the
# disk's procedural texture.
BH_DISK_ROTATION_SPEED = 0.8

# 6 7 Counter. Counts each time a wrist transitions from below to above its
# corresponding elbow — same definition as the original 67counter project. A
# rising-edge detector with hysteresis avoids re-firing on jitter near the
# elbow line: the wrist must clear the elbow by `SIXSEVEN_HYSTERESIS` (in
# normalised image coords, where 1.0 = full frame height) to count, and must
# fall the same distance below the elbow before another count is allowed on
# that side. Each arm is tracked independently, so an alternating pump fires
# two counts per cycle.
SIXSEVEN_MIN_VISIBILITY = 0.3
SIXSEVEN_HYSTERESIS = 0.01
# Frames over which the count-flash animation decays back to 0.
SIXSEVEN_FLASH_FRAMES = 12

# Onboarding / intro overlay.
# A brief "how to interact" splash shown once at startup (Nintendo-style),
# plus a persistent bottom-right hint that appears while a person is
# detected and has not interacted yet. Both demonstrate the pinch gesture
# with a small animated hand.
INTRO_DURATION_S = 3.0          # seconds the startup splash stays up
INTRO_FADE_S = 0.5              # fade-in / fade-out tail length (seconds)
HINT_PINCH_PERIOD_S = 1.6       # one open->close->open cycle of the demo hand
# The bottom-right hint retires permanently after the user first interacts,
# and also auto-expires this many seconds after it first appears (so it
# never lingers if the user just stands there without trying it).
HINT_TIMEOUT_S = 8.0
INTRO_TITLE = "HalLMediaPipe"
INTRO_SUBTITLE = "Gesture-controlled vision"
HINT_TEXT = "Close your hand to interact"


if __name__ == "__main__":
    print("config file, not supposed to be run directly")