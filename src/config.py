import math
import os

import mediapipe as mp

POSE_MODEL_PATH = "models/pose_landmarker_lite.task"
HAND_MODEL_PATH = "models/hand_landmarker.task"
IMAGE_FORMAT = mp.ImageFormat.SRGB

# Body-pose inference (HALL_POSE). OFF by default since 2026-07-07: nothing
# in the current UI needs the body skeleton (the pinch pipeline is entirely
# hand-relative), and MediaPipe pose on CPU was the single biggest CPU cost
# (~1.5 cores at ~13 fps). Setting HALL_POSE=1 re-enables it and brings back
# the pose-driven "6 7 Counter" (its button hides when pose is off).
POSE_ENABLED = os.environ.get("HALL_POSE", "0") == "1"

# Dev/testing: start straight in the Vtuber scene with the puppet spawned and
# kept alive (so the avatar can be driven from a recorded VIDEO FILE via
# HALL_CAMERA=<file> without needing live pinch gestures to navigate). Off in
# production. Implies the puppet's pose need, so pose runs.
START_VTUBER = os.environ.get("HALL_START_VTUBER", "0") == "1"

# Inference backend for the HAND pipeline (HALL_INFERENCE):
#   "mediapipe" — default; MediaPipe HandLandmarker (.task), CPU on the Jetson.
#   "gpu"       — onnxruntime palm-detection + handpose, able to use the CUDA
#                 execution provider on the Jetson (CPU fallback elsewhere).
HALL_INFERENCE = os.environ.get("HALL_INFERENCE", "mediapipe")

# Inference backend for the BODY-POSE pipeline (HALL_POSE_INFERENCE), analogous
# to HALL_INFERENCE for hands:
#   "mediapipe" — default; MediaPipe PoseLandmarker (.task), CPU (~13 fps on the
#                 Jetson, one inference behind — the body's stutter/lag source).
#   "gpu"       — onnxruntime BlazePose person-detection + pose-landmark, able to
#                 use CUDA/TensorRT on the Jetson (CPU fallback elsewhere). Both
#                 emit the same PoseLandmarkerResult surface, so the rest of the
#                 pipeline (smoother, rig, state) is identical for both. `hallrun`
#                 defaults this to "gpu" so the deployed body also runs on the GPU
#                 (frees the ~1.5 CPU cores CPU-pose ate and lifts the frame rate).
POSE_INFERENCE = os.environ.get("HALL_POSE_INFERENCE", "mediapipe")

# ONNX models for the "gpu" hand backend. Paths are relative to the repo root
# (the app runs from there, matching the .task paths above). Sourced from the
# OpenCV Model Zoo (opencv/opencv_zoo, Apache-2.0).
PALM_ONNX = os.environ.get("HALL_PALM_ONNX", "models/gpu/palm_detection_mediapipe_2023feb.onnx")
HAND_ONNX = os.environ.get("HALL_HAND_ONNX", "models/gpu/handpose_estimation_mediapipe_2023feb.onnx")

# ONNX models for the "gpu" pose backend (HALL_POSE_INFERENCE=gpu). The person
# detector is the OpenCV Model Zoo BlazePose detector (opencv/opencv_zoo,
# Apache-2.0, 224x224). The landmark model is tf2onnx-converted from the same
# pose_landmarks_detector that ships in models/pose_landmarker_lite.task, so its
# output matches what the MediaPipe path produced. Both gitignored (see models/).
POSE_DET_ONNX = os.environ.get(
    "HALL_POSE_DET_ONNX", "models/gpu/person_detection_mediapipe_2023mar.onnx")
POSE_LM_ONNX = os.environ.get(
    "HALL_POSE_LM_ONNX", "models/gpu/pose_landmark_lite.onnx")

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

# Optional cap on the TensorRT build workspace, in MiB (HALL_TRT_MAX_WORKSPACE).
# The Orin Nano has 8 GB of memory SHARED between CPU and GPU, and now runs four
# TRT engines when the Vtuber is active (palm + handpose + pose-detector +
# pose-landmark) alongside the browser kiosk and the black-hole shader. If that
# runs the board out of memory, cap each engine's build workspace here (e.g. 512
# or 1024) to bound peak GPU memory — the trade is a possibly slower engine.
# Unset (default) leaves TensorRT's own default workspace so the proven hand-only
# setup is unchanged; only set it if memory gets tight.
_TRT_MAX_WORKSPACE_MB = os.environ.get("HALL_TRT_MAX_WORKSPACE", "").strip()


def _provider_with_options(name):
    """Attach provider options to TensorRT (engine cache + FP16); pass any other
    provider through as a bare name. onnxruntime accepts a providers list that
    mixes plain names and ``(name, options_dict)`` tuples."""
    if name == "TensorrtExecutionProvider":
        opts = {
            "trt_engine_cache_enable": True,
            "trt_engine_cache_path": TRT_ENGINE_CACHE,
            "trt_fp16_enable": True,
        }
        if _TRT_MAX_WORKSPACE_MB:
            # onnxruntime expects the workspace size in BYTES.
            opts["trt_max_workspace_size"] = int(_TRT_MAX_WORKSPACE_MB) * 1024 * 1024
        return (name, opts)
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
# Appliance self-healing (web mode only): if the camera stops delivering
# NEW frames for this many seconds (V4L2 wedge — reads neither error nor
# return), the process EXITS so the kiosk supervisor can restart it with a
# fresh camera handle. 0 disables. Window/stream modes never self-exit.
CAMERA_STALL_S = float(os.environ.get("HALL_CAMERA_STALL_S", "10"))

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

# GPU hand backend (HALL_INFERENCE=gpu) ROI tracking, the fix for the
# hand-landmark quality collapsing near the frame border (the reason
# EDGE_MARGIN_FRAC keeps buttons away from it): a hand successfully
# landmarked last frame is re-cropped this frame from its OWN landmarks
# (MediaPipe's scheme); the palm detector only runs to fill empty hand
# slots. Palm detection is the stage that fails first near the edge — a
# partially visible palm scores below threshold and the hand vanished —
# while the landmark model keeps tracking a partially visible hand fine
# when handed a good crop. On the synthetic edge-pan bench this cut the
# edge-crossing landmark error from 11.2 to 4.7 px and kept the hand
# tracked (err 3-6 px) until only ~6 of 21 landmarks remained in frame.
# HALL_HAND_ROI_TRACK=0 restores the v1 palm-detect-every-frame behaviour
# (A/B knob for on-device tuning).
HAND_ROI_TRACKING = os.environ.get("HALL_HAND_ROI_TRACK", "1") == "1"

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

# Body-pose smoothing (POSE_SMOOTHER): the same One-Euro + velocity
# extrapolation the cursor gets, applied to every pose landmark (2D image +
# 3D world). Pose runs ~13 fps on CPU and one inference behind, so raw it
# stutters and lags while the faster, already-filtered hands feel fine. The
# filter kills the stutter/teleport-jumps; the extrapolation (output + filtered
# velocity × result age, capped) hides the latency so the body glides between
# results instead of freezing. Landmarks are normalized (2D) / metres (3D), so
# the cutoffs are lower than the pixel-space cursor's. Tune for smooth-at-rest,
# snappy-on-motion. Set HALL_POSE_SMOOTH=0 to bypass (raw passthrough).
POSE_SMOOTHING = os.environ.get("HALL_POSE_SMOOTH", "1") == "1"
# Tuned against a real clip replayed at the Jetson's ~13 fps pose rate: vs the
# raw "staircase" the body shows today, these cut the worst per-frame jump ~2.9x
# (glide, not stutter) for ~5% more lag, which the extrapolation then hides.
POSE_MIN_CUTOFF = 0.8
POSE_BETA = 0.4
POSE_EXTRAP_MAX_S = 0.12
# Re-init the filters after a gap this long (pose turned off then on again),
# so the body eases in from the new pose instead of snapping across the gap.
POSE_SMOOTH_RESET_GAP_S = 0.4

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

# --- Orbitals experiment (n-body gravity sandbox) -----------------------
# A pinch-driven gravity playground: place stars/planets/moons/comets and
# watch them orbit, slingshot and merge. The whole sim runs in SCREEN PIXELS
# (positions px, velocities px/s) with a tunable gravitational constant, so
# there is no metres<->pixels bridge to carry — everything the renderer
# needs is already in its own coordinates.
#
# Integration mirrors the slingshot's fixed-timestep discipline but uses
# velocity-Verlet (leapfrog) instead of RK4: it is SYMPLECTIC, so orbital
# energy stays bounded over long runs (RK4 slowly gains energy and spirals
# orbits outward). The sim-speed stepper (shared with the slingshot) changes
# how many sub-steps run per frame, never the step size.
ORB_G = 4000.0               # gravitational constant (px^3 / (mass * s^2))
# Plummer softening only regularises the force at true zero separation; it is
# kept SMALL (a couple of px) because hard-sphere collisions now stop bodies
# from ever overlapping, so gravity stays essentially exact (F = G m1 m2 / r^2)
# right down to contact instead of being fudged soft at close range.
ORB_SOFTENING_PX = 2.0
ORB_PHYS_DT = 1.0 / 240.0    # physics sub-step (s); small for fast fly-bys
ORB_FRAME_DT = 1.0 / 30.0    # simulated time one video frame represents (s)
ORB_MAX_SUBSTEPS = 40        # per-frame cap; drops sim debt rather than stall
ORB_TIME_SCALES = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0)  # sim speeds the UI steps
ORB_MAX_BODIES = 40          # hard cap; oldest placed body drops past it
ORB_TRAIL_LEN = 64           # client-accumulated trail length (points)
ORB_PRUNE_MARGIN = 1.6       # bodies beyond this * frame extent are removed
ORB_LAUNCH_GAIN = 2.6        # pull px -> launch px/s (pinch-drag-release)
ORB_MAX_PULL_PX = 260        # cap on the aim pull-back distance (px)
ORB_GRAB_PAD_PX = 26         # grab a body when the pinch lands within r + pad
ORB_PREDICT_TIME_S = 2.2     # how far ahead the dotted aim preview simulates
ORB_PREDICT_SAMPLE = 5       # one preview dot every N physics steps

# Collision OUTCOME model (Leinhardt & Stewart 2012 / standard N-body practice):
# what happens when two bodies touch is decided by the impact speed relative to
# their MUTUAL ESCAPE VELOCITY  v_esc = sqrt(2 G M_tot / R_tot):
#   * v_impact <= v_esc                      -> MERGE (perfect accretion): they
#       are too slow to escape each other's gravity, so they fuse into one body
#       conserving mass + momentum (radius recombined by volume). Flash on fuse.
#   * v_esc < v_impact <= FRAG*v_esc         -> BOUNCE (hit-and-run): a
#       hard-sphere impulse with restitution deflects both by their mass ratio
#       (a light asteroid is flung, a star barely shifts).
#   * v_impact > FRAG*v_esc                   -> FRAGMENT (catastrophic
#       disruption): the impact energy shatters both into a largest remnant +
#       debris particles that fly out conserving total mass + momentum (and then
#       gravitate again — reaccumulation). This is the "breaks into particles".
ORB_RESTITUTION = 0.5            # bounce coefficient of restitution (hit-and-run)
ORB_COLLISION_SLOP = 0.5        # px overlap left uncorrected (anti-jitter)
ORB_FRAG_VESC_FACTOR = 2.4      # v_impact / v_esc above which bodies shatter
ORB_FRAG_COUNT = 7              # debris fragments a catastrophic impact makes
ORB_FRAG_LR_FRACTION = 0.45     # mass fraction kept in the largest remnant
ORB_FRAG_SPEED = 0.45           # debris scatter speed as a fraction of v_impact
ORB_FRAG_MIN_MASS = 0.5         # bodies lighter than this don't fragment further
ORB_FLASH_DECAY = 0.045         # per-frame decay of the impact/merge flash (0..1)

# Body-type presets the palette spawns: (mass, radius px, [r, g, b] 0-255).
# Masses/radii are chosen so a Star holds Planets/Moons in visible orbits
# and a Comet is a light streaker. Colours are a rough blackbody-ish ramp
# hot->cool: white-gold star, blue planet, grey moon, icy-cyan comet.
ORB_BODY_TYPES = {
    "star":   {"mass": 1200.0, "radius": 26, "rgb": [255, 226, 158]},
    "planet": {"mass": 42.0,   "radius": 13, "rgb": [110, 170, 255]},
    "moon":   {"mass": 9.0,    "radius": 8,  "rgb": [200, 205, 215]},
    "comet":  {"mass": 2.5,    "radius": 6,  "rgb": [150, 240, 255]},
}
ORB_DEFAULT_KIND = "planet"

# --- Waves experiment (interactive ripple tank) --------------------------
# A 2D ripple tank: pinch on empty water to drop an oscillating point
# source, pinch an existing source to drag it around (its wake compresses
# ahead / stretches behind — a live Doppler pattern), and two or more
# sources paint a standing interference pattern. Python owns the SOURCES
# (placement, dragging, palette — all logic/hit-testing); the FIELD is pure
# rendering and is integrated by the sink: the browser steps the 2D wave
# equation in a WebGL ping-pong texture (web/src/gl/WavesLayer.tsx), and
# the cv2 window/stream fallback runs the same finite-difference scheme in
# numpy at low resolution. Screen edges reflect like real tank walls.
WAVE_MAX_SOURCES = 6         # also the shader's uniform array size — keep
                             # web/src/gl/waves_step.frag.glsl in sync
WAVE_SPEED_PX_S = 340.0      # propagation speed c (frame px / s at 1x)
WAVE_TIME_SCALES = (0.25, 0.5, 1.0, 2.0, 4.0)  # -/+ stepper values
WAVE_FRAME_DT = 1.0 / 30.0   # simulated seconds one video frame represents
WAVE_GRAB_PAD_PX = 46        # pinch-grab radius around a source centre
WAVE_AMP = 1.0               # source amplitude (field units; render maps ~1
                             # to full crest brightness)
WAVE_RAMP_S = 0.3            # source onset ramp, avoids a shock front
# Field ring-down time constant (s) — how far a ripple travels before fading.
# This is the knob that decides whether the tank reads or turns to soup: the
# decay LENGTH is c * tau, so 0.9 s ~= 306 px against a 1280 px frame. Waves
# stay local to their source and the far field goes calm (so the camera image
# shows through and the pattern is readable), while two sources a few hundred
# px apart still overlap strongly enough to show clean interference fringes.
# Measured at 1280x720, 2 sources: raising this to 1.6 s barely strengthens the
# interference zone (+17%) but more than doubles the far-field fill (+115%) —
# i.e. it just washes the frame. Lower = more local; higher = longer reach.
# (An absorbing "beach" border was tried here and REJECTED: with this damping,
# reflections already return at ~10%, so it changed the far field by ~16% and
# did not earn its complexity.)
WAVE_DECAY_TAU_S = 0.9
# Physics sub-step (s). The leapfrog update `u_next = 2u - u_prev + s^2*lap`
# assumes a CONSTANT dt — `u_prev` lives at `t - dt`, so a step that changes
# dt silently mismatches the time levels and PUMPS energy every frame. That
# bug made the field diverge to ~1e32 in 5 s (it read as the screen
# saturating). Both renderers now bank time and step in whole WAVE_PHYS_DT
# chunks, exactly like the Orbitals sim does with ORB_PHYS_DT — never derive
# a sub-step from the frame remainder.
# Stability (CFL): needs s = c*dt/dx <= ~0.86 for the 9-point stencil. At the
# FINEST grid either renderer uses (the shader's frame/4 -> dx=4 px):
# s = 340*(1/240)/4 = 0.35. Comfortable on both paths.
WAVE_PHYS_DT = 1.0 / 240.0
WAVE_MAX_SUBSTEPS = 16       # per-frame cap; drops sim debt rather than stall
WAVE_MAX_DEBT_S = 0.25       # after a stall, integrate at most this much

# Palette presets: the oscillation frequency the next placed source gets.
# With c = 340 px/s these give wavelengths of ~280 / ~140 / ~85 px — "low"
# reads as slow rolling swells, "high" as tight ripples, and two "mid"
# sources a few hundred px apart show textbook two-slit fringes.
WAVE_SOURCE_TYPES = {
    "low":  {"freq": 1.2, "label": "Low"},
    "mid":  {"freq": 2.4, "label": "Mid"},
    "high": {"freq": 4.0, "label": "High"},
}
WAVE_DEFAULT_KIND = "mid"
# cv2 fallback field only (the WebGL path has its own grid): sim cell size
# in frame px. 8 px/cell keeps the numpy grid ~160x90 at 720p.
WAVE_GRID_PX = 8

# Display tone curve, shared by both renderers (mirrored in
# web/src/gl/waves_render.frag.glsl — keep in sync). The water tint's opacity
# is `MAX_ALPHA * tanh(|u| * GAIN)` rather than a plain linear ramp, because
# the field's amplitude scales with how many sources are running: measured
# max|u| is ~0.5 for one source but ~1.2 for six. A linear ramp bright enough
# to show a single source's ripples would white out at six. tanh is steep near
# zero (faint ripples become clearly visible) and saturates gently (six sources
# land just above one instead of 6x), so one curve serves both ends.
WAVE_DISPLAY_GAIN = 1.8
WAVE_DISPLAY_MAX_ALPHA = 0.85

# --- Charges experiment (electrostatic field) ---------------------------
# Pinch empty space to drop a point charge of the palette's selected sign
# and magnitude; pinch a charge to drag it and watch the field reorganise.
#
# The charges are STATIC — they do not accelerate each other. That is a
# deliberate design choice, not a missing feature: with an inverse-square
# attraction and no orbital velocity, a +/- pair would simply collide
# instantly and the whole thing would collapse into Orbitals-with-signs.
# Real electrostatics exhibits pin the charges precisely because the FIELD
# is the subject, not the particles. Consequently this experiment has NO
# time integration at all (no dt, no CFL, no sub-steps): the potential is
# evaluated analytically, V = k * sum(q_i / r_i), per pixel by the shader.
#
# Python owns only the charge LIST (place / drag / palette). Everything
# visual is derived from it by the renderer: the browser colours V + its
# equipotential contours in a single-pass analytic shader
# (web/src/gl/ChargesLayer.tsx) and traces the field lines in JS
# (web/src/overlay/scene.ts), the same way it already accumulates Orbitals'
# trails client-side. The cv2 window/stream fallback does both in numpy.
CHG_MAX = 8                  # hard cap; also the shader's uniform array size
                             # — keep web/src/gl/charges.frag.glsl in sync
CHG_GRAB_PAD_PX = 46         # pinch-grab radius around a charge centre
CHG_K = 90000.0              # Coulomb constant in screen units: V is in
                             # "volts" of k*q/r with r in px and q in the
                             # palette's units. Only sets the scale of the
                             # equipotential spacing + colour ramp.
# Palette presets: (charge, label). Sign is the physics; magnitude lets a
# 2q charge visibly dominate its neighbour (twice the field lines).
CHG_TYPES = {
    "neg2": {"q": -2.0, "label": "-2q"},
    "neg1": {"q": -1.0, "label": "-q"},
    "pos1": {"q": 1.0, "label": "+q"},
    "pos2": {"q": 2.0, "label": "+2q"},
}
CHG_DEFAULT_KIND = "pos1"
# Softening (px) on r in the field/potential sums. Without it V and |E| blow
# up at a charge's own centre (1/r and 1/r^2 singularities) and the shader
# renders a saturated disk; this rounds the core off at roughly the marker's
# own radius, where nothing is being taught anyway.
CHG_SOFTEN_PX = 14.0
# Field lines: how many leave a unit charge (a 2q charge gets twice as many,
# which is exactly the textbook convention that line DENSITY encodes |q|).
CHG_LINES_PER_Q = 12
CHG_LINE_STEP_PX = 6.0       # streamline integration step (RK2)
CHG_LINE_MAX_STEPS = 320     # give up after this many (bounds a stray line)

# Flowing arrowheads along the field lines (mirrored in
# web/src/overlay/scene.ts — keep in sync). They ride the SAME traced
# polylines, so the geometry is untouched; they only show which way the field
# points: out of + charges, into - ones. Arc length along a line is exactly
# `index * CHG_LINE_STEP_PX` (the tracer steps a fixed distance), so finding
# the vertex under an arrow is a divide rather than a search.
CHG_ARROW_SPACING_PX = 46.0  # arc length between arrows on one line
CHG_ARROW_SPEED_PX_S = 34.0  # how fast they crawl along it
CHG_ARROW_LEN_PX = 9.0
# |E| that maps to a full-strength arrow. Arrow size/opacity come from the
# LOCAL |E|, which is what makes cancellation visible for free: at the null
# point between like charges |E| is exactly 0, so those arrows shrink to
# nothing on their own — no special case. The far field fades too, which keeps
# the picture clean. ~3 puts a unit charge's arrows at full strength ~150 px out.
CHG_ARROW_E_REF = 3.0
# Equipotential contour spacing (in the same V units as CHG_K). The shader
# draws a band every multiple of this.
CHG_EQUIPOT_STEP = 900.0
# cv2 fallback only: potential is evaluated on a grid this coarse (px/cell)
# and upscaled, mirroring the Waves fallback's approach.
CHG_GRID_PX = 8

# --- Spacetime experiment (relativistic gravity) -------------------------
# The rubber-sheet picture, done honestly. Pinch empty space to drop a mass
# and the grid sags into a well; pinch a mass to drag it and the curvature
# follows. Pinch with BOTH hands at once to orbit the camera in 3D (see the
# ST_ROT_* gains) — two pinches supersede place/drag, the same way a
# two-finger gesture supersedes a one-finger pan on a touchscreen.
#
# One geometry drives everything: each mass gets a Schwarzschild radius
# rs = ST_RS_PER_MASS * m (px), and that SAME rs feeds both the sheet's shape
# and the orbit dynamics — so what you see and what the particles feel are the
# same spacetime rather than two unrelated effects. Fixing rs per unit mass
# fixes the speed of light in screen units too (rs = 2GM/c^2 => c^2 =
# 2*ST_ORB_G/ST_RS_PER_MASS), which is why there is no separate `c` knob.
#
# SOURCES (every formula below is one of these, not something invented here):
#   [Flamm 1916]  L. Flamm, "Beitraege zur Einsteinschen Gravitationstheorie",
#                 Phys. Z. 17, 448 (1916). The original embedding; reprinted as
#                 a Golden Oldie in Gen. Rel. Grav. 47, 72 (2015).
#   [Schwarzschild 1916b]  K. Schwarzschild, interior solution for an
#                 incompressible sphere, Sitzungsber. Preuss. Akad. Wiss. 424.
#   [MTW 1973]    Misner, Thorne & Wheeler, "Gravitation", Box 23.2 / Fig 23.1:
#                 the star embedding = interior spherical CAP + exterior Flamm
#                 paraboloid, joined with a common tangent at the surface.
#   [PW 1980]     Paczynski & Wiita, A&A 88, 23: pseudo-Newtonian potential.
#   [BPT 1972]    Bardeen, Press & Teukolsky, ApJ 178, 347: the Kerr ISCO.
#   [Mukhopadhyay 2002]  ApJ 581, 427: pseudo-Newtonian Kerr force.
#   [Thorne 1974] ApJ 191, 507: the a* <= 0.998 spin-up limit.
#   [Lense-Thirring 1918]  Phys. Z. 19, 156: frame dragging.
#
# THE SHEET is the textbook embedding of the equatorial slice, and a body's
# RADIUS is what makes it interesting — this is the correction that matters:
#
#   * OUTSIDE the body (r >= R): Flamm's paraboloid, z(r) = 2*sqrt(rs*(r-rs)).
#     [Flamm 1916]
#   * INSIDE it (r < R): the interior Schwarzschild solution embeds as a
#     SPHERICAL CAP of radius A = sqrt(R^3/rs) — a smooth, shallow bowl with no
#     throat at all. It meets the paraboloid with a COMMON TANGENT at r = R
#     (both slopes are sqrt(rs/(R-rs)) there — verified numerically in tests).
#     [Schwarzschild 1916b], [MTW 1973 Box 23.2]
#
# This is why a star and a black hole are not the same picture, and the earlier
# version of this file got it WRONG. Treating a star as a point mass gives it a
# full funnel down to its own rs — i.e. draws every star as a black hole. A real
# star's surface sits far outside its rs (the Sun: R/rs ~ 2.4e5), so its funnel
# is amputated at the surface and replaced by a gentle cap. A black hole has NO
# surface: the funnel runs all the way to the horizon, where dz/dr -> infinity
# and the sheet goes VERTICAL. That cliff — not depth — is what "black holes
# deform space much more" actually means.
#
# Worth being precise about the depth, because intuition oversells it: Flamm
# depth goes as sqrt(rs) ~ sqrt(M), so 4x the mass is only 2x deeper. By
# Birkhoff's theorem a 1 Msun star and a 1 Msun hole have IDENTICAL geometry
# outside the star's surface — the far field cannot tell them apart. The drama
# is entirely COMPACTNESS: how far down the funnel you are allowed to go.
#
# Caveat, unchanged: summing one-mass embeddings is NOT a solution of Einstein's
# equations — they are nonlinear, so two wells do not superpose. It is the
# standard visual approximation and is exact for the single-mass case.
#
# THE ORBITS use a pseudo-Newtonian stand-in for the geodesics. For a
# non-spinning body that is Paczynski-Wiita, a = -G*M/(r - rs)^2 — moving the
# pole from the centre to the HORIZON is the whole trick, and it buys the two
# things Newtonian gravity cannot show: perihelion PRECESSION (the ellipse
# rotates; the Mercury effect) and an ISCO at r = 3*rs, inside which no
# circular orbit exists and the particle spirals in and is swallowed.
#
# Since the bodies SPIN (see ST_MASS_TYPES' `spin`), the force is Mukhopadhyay
# (2002)'s Kerr generalisation, in units G = M = c = 1 with x = r/r_g:
#
#     F(x) = (x^2 - 2*a*sqrt(x) + a^2)^2 / ( x^3 * (sqrt(x)*(x - 2) + a)^2 )
#
# chosen over hand-rolling something because it is CONSTRUCTED to give the
# exact Kerr ISCO (measured here: 0.0% error at every spin from -0.998 to
# +0.998), and because at a = 0 it collapses to 1/(x-2)^2 — i.e. to
# Paczynski-Wiita, to machine precision. So spin is a strict generalisation: a
# non-spinning scene behaves exactly as it did before spin existed, and the
# measured 47 deg/lap precession is untouched.
#
# The headline consequence, and the reason spin is worth the complexity: the
# ISCO becomes DIRECTIONAL. Co-rotating with an extremal hole you can hold an
# orbit down to 1.24 r_g; counter-rotating you cannot get closer than 8.99;
# without spin it is 6.00 either way. Space is being dragged, and which way you
# swim in it changes where you can survive. `a` in F() is signed by the orbit's
# own direction, so this falls out rather than being special-cased.
#
# Python owns the mass/orbiter lists, the camera angles and the integration;
# both renderers derive the picture. The projection + depth math is mirrored in
# web/src/overlay/scene.ts — keep the two in sync.
ST_MAX_MASSES = 6
ST_MAX_ORBITERS = 12
ST_GRAB_PAD_PX = 46
# Schwarzschild radius (px) per unit mass. This single number sets the whole
# experiment's REGIME, so it is the most consequential constant in the file.
#
# It was 9.0, which put orbits ~5 rs out and bodies at v/c ~ 0.47 — a regime
# where the post-Newtonian series is quantitatively worthless (1PN corrections
# ~22%, and the next order is not much smaller). 2.5 puts a typical orbit
# 20-40 rs out at v/c ~ 0.11-0.16, where 1PN error is a couple of percent and
# the physics on screen is honest.
#
# The visuals barely pay for it, which is why this is the right trade: well
# depth goes as sqrt(rs) (so ~40% shallower, still hundreds of px) and
# perihelion precession as rs/a (~20 deg per lap at 25 rs — still unmistakable).
# What actually shrinks is the horizon disk, which buys ROOM for orbits.
ST_RS_PER_MASS = 2.5
ST_CURV_REACH_PX = 460.0     # radius at which a well is declared flat again
# Vertical scale of the sheet. 1.0 = TO SCALE: z and r are both lengths in the
# same px, so the paraboloid is plotted exactly as [Flamm 1916] gives it, with
# no vertical exaggeration whatsoever. It was 1.25 with a tanh ceiling on top;
# both are gone, because they were the two things making a hole look like a
# deep star instead of a different object. Leave this at 1.0.
ST_DEPTH_GAIN = 1.0
# The tanh depth ceiling that used to live here has been REMOVED, deliberately.
# It squashed the exact thing that should be dramatic: with it, a Hole came out
# 189 px deep against a Star's 82 px — a 2.3x difference standing in for what
# should be a smooth bowl versus a bottomless vertical funnel. Its stated job
# was taming the "tangle" of near-parallel lines at the throat, but that tangle
# is not an artefact to hide: dz/dr genuinely diverges at the horizon, and
# converging lines are what a vertical cliff LOOKS like. Stars no longer have a
# throat at all (they have a cap), so only holes show it — correctly.

# Mass presets: (m, label, rgb, spin). `compact` marks a horizon-sized body
# drawn as a black disk — same mass scale, but its rs is where the sheet's
# throat is, so it is the one preset where the horizon is visibly bigger than
# the marker.
#
# `spin` is the DIMENSIONLESS Kerr spin a* = Jc/(GM^2), in [0, 1). Astrophysics
# picks the numbers: real stars are slow rotators in these units (the Sun is
# a* ~ 2e-6 — utterly invisible, so "Star" gets a token spin purely so the
# marker turns), while accreting black holes are commonly measured near
# extremal. 0.998 is the Thorne limit — radiation capture stops accretion
# spinning a hole past it, so a* = 1 is not physical and is not offered.
# `r_over_rs` is the body's COMPACTNESS R/rs — the parameter that decides
# whether you get a bowl or a funnel, and now the whole point of the palette.
#
# It is also the one number here that is CHOSEN rather than derived, so be
# straight about it: real stars are nowhere near this compact (Sun R/rs = 2.4e5,
# white dwarf ~ 4e3), and at any scale where a hole's horizon is a visible disk
# a Sun-like star's bowl is flat to well under a pixel. That is not a rendering
# failure, it is the actual physics — normal matter barely curves spacetime.
# So the palette lives in the strong-field regime where the comparison fits on
# one screen: R/rs = 6 is roughly neutron-star territory (a real neutron star
# is ~2.9), which is the least compact thing that still visibly bends a 720 px
# frame. The GEOMETRY is exact; only this parameter is staged.
#
# `compact` (bool) means "no surface — this IS its horizon", i.e. a black hole.
# The palette IS the lesson, and it is the canonical Sun / neutron star / black
# hole trio: three objects of comparable mass whose wells look nothing alike,
# because what sets the shape is how far down the funnel their surface lets you
# go. The Sun is a big ball in a shallow dimple with NO funnel; the neutron star
# is a small ball at the bottom of a long one; the hole is a tiny disk with a
# funnel that runs to a vertical throat.
ST_MASS_TYPES = {
    # Sun: R/rs is STAGED (real value 2.4e5 — at that compactness the whole
    # frame sits inside the star and the sheet is exactly flat, which is true
    # and useless). 20 is the least compact thing that still visibly dimples.
    "sun":     {"m": 1.0, "label": "Sun", "rgb": [255, 214, 120],
                "compact": False, "r_over_rs": 20.0, "spin": 0.1},
    # Neutron star: R/rs = 2.9 is REAL (M ~ 1.4 Msun, R ~ 12 km, rs ~ 4.1 km).
    # Nothing is staged here — this is what a neutron star's well looks like.
    "neutron": {"m": 1.4, "label": "Neutron", "rgb": [190, 225, 255],
                "compact": False, "r_over_rs": 2.9, "spin": 0.5},
    # R = rs: no surface to stop the funnel. The SMALLEST marker on screen and
    # by far the deepest well — the lesson, not an accident.
    "bh":      {"m": 4.0, "label": "Hole", "rgb": [18, 16, 26],
                "compact": True, "r_over_rs": 1.0, "spin": 0.9},
}
ST_DEFAULT_KIND = "sun"
ST_SPIN_MAX = 0.998          # Thorne limit
# Visual rotation rate of a marker, as a fraction of the body's own horizon
# angular velocity Omega_H = a*c^3 / (2GM(1 + sqrt(1 - a*^2))). Scaled down
# because Omega_H at a* = 0.9 is genuinely thousands of rad/s in screen units
# — accurate and completely unwatchable. The RATIO between bodies is preserved,
# so a fast hole still visibly outspins a slow star. Display only.
ST_SPIN_VIS_SCALE = 4.0e-4
# Frame dragging (Lense-Thirring). A spinning mass drags spacetime around with
# it at omega = 2GJ/(c^2 r^3) — the far-field form, exact to leading order.
# This twists the grid azimuthally near a spinning body, which is the whole
# "black holes deform space so much" point: they do not just dent it, they
# WIND it. The 1/r^3 falloff makes it a tight local swirl, unlike the well.
ST_LT_TWIST_GAIN = 1.0       # multiplier on the twist's visual amplitude
ST_LT_TWIST_MAX_RAD = 1.1    # cap, so the grid cannot wind into a solid disk
# The "Orbiter" palette entry places a test particle instead of a mass.
ST_ORBITER_KIND = "orbiter"
ST_ORBITER_RGB = [140, 235, 255]

# --- View mode: 2D sheet vs 3D volumetric lattice ------------------------
# Two honestly different pictures of the same geometry, toggled by a button:
#
#   SHEET (2D)   — the classic embedding diagram: ONE 2D slice of space, bent
#                  into a third dimension that is not really there. It is the
#                  famous image, and it is also the one that quietly lies:
#                  people read the ball as "rolling downhill", i.e. gravity
#                  explained by gravity.
#   LATTICE (3D)  — a volume of space, compressed radially toward each mass.
#                  No fake extra dimension, no downhill: the grid itself is
#                  denser near the mass, which is what curvature actually does
#                  to distances. This is the picture the reference shows.
#
# The lattice's radial map is Schwarzschild's ISOTROPIC coordinate relation,
# not an art-directed pull. Areal radius r relates to isotropic radius rbar by
# r = rbar * (1 + rs/(4*rbar))^2, which inverts to
#     rbar = ((r - rs/2) + sqrt((r - rs/2)^2 - rs^2/4)) / 2,   r >= rs
# and puts the horizon at rbar = rs/4 — a real 4x compression at the horizon,
# tapering with distance. Drawing a uniform lattice at rbar instead of r gives
# exactly the pinch in the reference, from the metric rather than by eye.
# (Superposed over several masses, with the same caveat as the sheet: GR is
# nonlinear, so this is exact for one mass and an approximation for many.)
ST_VIEW_3D_DEFAULT = False   # open on the sheet; the button switches
# Lattice resolution. Much coarser than the sheet's grid ON PURPOSE: this is
# ST_LATTICE_LAYERS stacked grids plus verticals, so cost scales with the
# layer count and the Jetson kiosk pays it in Canvas2D.
ST_LATTICE_LAYERS = 5
ST_LATTICE_COLS = 12
ST_LATTICE_ROWS = 8
ST_LATTICE_SAMPLES = 44
ST_LATTICE_DEPTH_PX = 300.0  # vertical extent of the lattice box (px). Kept
                             # well under the reach: layers further out than
                             # ST_CURV_REACH_PX from a mass feel nothing and
                             # just add flat clutter.
ST_LATTICE_MARGIN = 1.15     # slightly larger than the frame, so a mass placed
                             # anywhere the user can reach is INSIDE the volume.
                             # The box edges therefore sit just off-screen — the
                             # reference is a standalone model that can show its
                             # own corners; an AR overlay reads better as "space
                             # fills the view".
ST_LATTICE_VERTICALS = True  # the box's vertical struts; off = layers only
ST_LATTICE_VERT_STRIDE = 2   # ...but only every Nth node, or 100+ struts turn
                             # the volume into a hairball
# Display exaggeration of the radial pull, the lattice's answer to
# ST_DEPTH_GAIN. Needed because the isotropic map is HONEST and therefore tiny:
# the offset saturates at rs/2, which is ~18 px for the Hole preset against a
# 720 px frame — a real effect nobody would ever see. The MAP is the metric's;
# only its amplitude is turned up, and (as with the sheet) the orbits never
# read any of it.
ST_LATTICE_GAIN = 7.0

# Grid: how many lines each way, and how finely each line is sampled. The
# sample count is what makes a line CURVE through the well, so it is much
# higher than the line count (a 24x14 grid sampled at its crossings only would
# render the funnel as a coarse polygon).
ST_GRID_COLS = 30
ST_GRID_ROWS = 18
ST_LINE_SAMPLES = 72
# Sheet extent as a fraction of the frame. Sized for the YAWED case, not the
# default one: the sheet is a finite patch, so at 1.25 a 70-degree yaw swings
# its corner into view and leaves a bare triangle. 1.7 keeps the edges out of
# frame through a full spin; cols/rows are scaled with it to hold cell density.
ST_GRID_MARGIN = 1.7

# Camera — a TURNTABLE (yaw about the sheet's normal + elevation), not an
# arcball. The sheet has a real "up", so preserving it is what keeps the view
# legible; arcball's unrestricted spin would let a visitor tumble the scene to
# an unreadable angle with no way back. Blender defaults to turntable for the
# same reason.
#
# `pitch` is elevation above the sheet: 90 deg is straight down, 0 is edge-on,
# 180 deg is edge-on from the far side, 270 deg is straight up from underneath.
#
# It is UNCLAMPED — pitch accumulates freely like yaw, so the camera can orbit
# all the way around and look at the sheet from below. Turntable cameras
# usually cap elevation to stop the view going upside down, and this one did
# (first 89 deg, then 90); both were wrong for an exhibit. The projection has
# no singularity anywhere: at pitch > 90 you simply cross over the top and see
# the underside of the well, which for a funnel is worth seeing. Nothing here
# needs a limit, so there isn't one.
#
# Consequence to preserve: pitch must NOT be wrapped into [0, 2pi). Keeping it
# continuous is what lets the easing and the frontend's lerp (state/interp.ts)
# stay plain — a wrap would make them take the long way round at the seam.
ST_YAW_DEFAULT_RAD = 0.0
ST_PITCH_DEFAULT_RAD = math.radians(34.0)   # classic three-quarter view
ST_PITCH_TOP_RAD = math.radians(90.0)       # the "Top" button's exact XY view
ST_FOCAL_PX = 1700.0         # perspective focal length; larger = flatter
ST_ZOOM_MIN, ST_ZOOM_MAX = 0.55, 2.4

# --- Two-hand camera control: hybrid position/rate (RubberEdge-style) -----
#
# v1 was a plain INCREMENTAL drag (angle += midpoint delta * gain) and it was
# rightly called crude. Two failures, both structural:
#   1. Reaching a top-down view needed ~240 px of sustained upward travel with
#      BOTH pinches held — which ends with the hands near the frame edge, the
#      exact place `manager.EDGE_MARGIN_FRAC` documents the landmark model
#      degrading. The pinch drops, the gesture dies half-way, top view is
#      effectively unreachable.
#   2. Incremental means the mapping has no home: returning your hands to where
#      they started does NOT return the view, so nothing is aimable.
#
# The fix follows the HCI literature rather than taste. Zhai & Milgram's 6-DOF
# taxonomy says the good pairings are isotonic->position and isometric->rate;
# a hand is ISOTONIC (free-moving, no resistance), so rate control alone would
# be the bad pairing. But pure position control can't cover unbounded rotation
# from a bounded workspace without clutching, and clutching is what wrecked v1.
# Casiez et al.'s RubberEdge resolves exactly this: POSITION control inside a
# disc around the grab origin, blending to RATE control outside it — measured
# ~20% better than position control when clutching is significant.
#
# So: within ST_CAM_POS_RADIUS_PX of where the two-pinch started, hand offset
# maps ABSOLUTELY to an angle offset (precise, aimable, has a home). Push past
# the disc and the excess becomes angular VELOCITY, so you can spin forever
# from a small, comfortable, well-tracked region near the frame centre.
ST_CAM_POS_RADIUS_PX = 150.0
ST_CAM_YAW_POS_GAIN = 0.0075    # rad per px inside the disc (~64 deg at the rim)
ST_CAM_PITCH_POS_GAIN = 0.0075
ST_CAM_YAW_RATE_GAIN = 0.011    # rad/s per px of excess beyond the disc
ST_CAM_PITCH_RATE_GAIN = 0.009
ST_CAM_RATE_MAX_RAD_S = 2.2     # ~1 turn / 3 s at full push; fast but trackable
# Zoom is position-controlled from the grab's opening span, with a deadzone so
# the hands' natural drift while yawing does not smuggle in a zoom.
ST_ZOOM_DEADZONE = 0.07
# Camera easing (0..1 per frame): the rendered angles chase the gesture target,
# killing the tremor a bare hand cannot avoid. Also drives the view-toggle
# animation, so it doubles as the snap-to-view speed.
ST_CAM_SMOOTH = 0.25

# Orbit integration. Velocity-Verlet in fixed ST_PHYS_DT chunks, exactly like
# Orbitals (see the ORB_PHYS_DT note: never derive a sub-step from the frame
# remainder).
#
# EVERYTHING GRAVITATES. The masses used to be pinned (copying Charges' "the
# field is the subject" call); that was wrong for gravity, where the bodies are
# not sources of a backdrop, they ARE the system. Every body now pulls every
# other one pairwise, orbiters included — a test particle is just a light body.
#
# THE DYNAMICS ARE POST-NEWTONIAN (EIH, 1PN) — see ST_PN_* below. The previous
# version applied a TEST-PARTICLE pseudo-potential pairwise, which has no
# validity for comparable masses; this replaces it with the real N-body
# relativistic framework.
#
# On "just use numerical relativity": it is not a matter of effort. NR means
# integrating Einstein's field equations on a 3D grid (BSSN/Z4c, moving
# punctures, AMR). A 2025 binary-neutron-star merger covering 1.5 SECONDS took
# 130 MILLION CPU-hours on Fugaku across 20k-80k cores. This board has 6 cores
# and needs 30 fps. That is ~9 orders of magnitude; no optimisation crosses it,
# and nothing about the gap is Python's fault. EIH is not a consolation prize
# either: it is the same framework JPL's DE440 ephemeris uses to place the
# planets to metre accuracy.
# G is fixed by wanting a READABLE orbit, then everything else follows: a Star
# (m=1) at r=180 px comes out at v_circ = sqrt(G*m*r)/(r-rs) ~= 162 px/s, i.e.
# one lap every ~7 s. Note this puts the orbiter at only ~20 rs — deep in the
# strong field, where PW precession is ~45 deg per lap and unmistakable. Real
# Mercury (r ~ 2.5e7 rs) precesses 43 arcsec per CENTURY; the effect is honest,
# the regime is chosen so a person can see it in one visit.
ST_ORB_G = 4.2e6             # px^3 / (mass * s^2)
ST_PHYS_DT = 1.0 / 240.0
ST_FRAME_DT = 1.0 / 30.0
ST_MAX_SUBSTEPS = 40
ST_TIME_SCALES = (0.25, 0.5, 1.0, 2.0, 4.0)
ST_ORB_TRAIL_LEN = 360       # ~2 laps at 1x — enough to see the axis walk
# Anything beyond this * frame extent is removed — masses AND orbiters. With
# everything gravitating, a close encounter can sling a body off-screen, and an
# off-screen mass would keep pulling the scene with no visible cause. 1.8 is
# just past the drawn sheet (ST_GRID_MARGIN 1.7) and matches the widest view
# (min zoom 0.55 shows ~1.8x the frame), so a body vanishes only once no
# camera setting could still show it. A grabbed mass is never pruned.
ST_PRUNE_MARGIN = 1.8
# Spawn velocity as a fraction of the local circular speed. 1.0 would give a
# circle, which precesses invisibly (a rotating circle looks identical); 0.72
# gives a clearly eccentric ellipse whose axis visibly walks around.
ST_ORB_SPAWN_VFRAC = 0.72
ST_ORB_MIN_SPAWN_RS = 3.4    # spawn no closer than this * rs — just outside
                             # the ISCO at 3*rs, so a fresh orbiter is stable
ST_CAPTURE_FLASH_DECAY = 0.04
# Mass of an "Orbiter" — small, but NOT zero: it gravitates back on everything,
# because the ask was that every object interact. Its rs is ~0.2 px, so its own
# well is invisible and it still behaves as a test particle to the eye.
ST_ORBITER_MASS = 0.02
# A newly placed body is given a near-circular orbit about the dominant mass
# already on screen (solved from the real field, not a closed form). Placing it
# at rest would be equally physical and much less useful — with everything now
# gravitating, a sandbox of bodies dropped at rest just collapses to a merger in
# seconds. 1.0 = circular; the ORBITER palette entry keeps its own eccentric
# ST_ORB_SPAWN_VFRAC so it visibly precesses.
ST_MASS_SPAWN_VFRAC = 1.0

# --- Gravitational waves ------------------------------------------------
# A bound pair radiates orbital energy as gravitational waves and spirals in.
# This is not decoration: it is why binaries merge at all, and it is the whole
# LIGO story. Rate from [Peters 1964] (Eq. 5.6/5.9) for a circular orbit:
#
#     P    = (32/5) * G^4 * (m1*m2)^2 * (m1+m2) / (c^5 * r^5)
#     da/dt= -beta / a^3,  beta = (64/5) * G^3 * m1*m2*(m1+m2) / c^5
#     t_merge = (5/256) * (c^5/G^3) * a^4 / (m1*m2*(m1+m2))
#
# Implemented as an equal-and-opposite drag along the pair's RELATIVE velocity,
# sized so the pair loses energy at exactly P. That conserves momentum by
# construction and reproduces Peters' merger time for circular orbits (asserted
# in tests/smoke_scenes.py against the closed form above).
#
# TWO honest limitations, and the second one is the big one:
#
# 1. P is evaluated with the CIRCULAR formula at the current separation. Peters
#    & Mathews (1963) give the general instantaneous power for an eccentric
#    orbit; an eccentric pair here radiates at the circular rate for its
#    separation, understating the loss near periapsis.
#
# 2. Peters is a LEADING-ORDER quadrupole result and assumes v << c. This
#    sandbox does not: two Holes at 160 px orbit at v/c ~ 0.47 (measured), and
#    even at 300 px it is ~0.35. That is the regime where real work needs high-
#    order post-Newtonian or full numerical relativity — the quadrupole formula
#    is quantitatively out of its depth here, and the inspiral RATE should be
#    read as indicative, not predictive. What is solid: the drag removes energy
#    at exactly the rate the formula states (verified to 0.000%), momentum is
#    conserved to 1e-9, and the qualitative story — bound pairs spiral in and
#    merge, tighter pairs merge sooner — is right.
#
# The root cause of (2) is that the palette is deliberately strong-field: a Hole
# has rs = 36 px and orbits live a few rs out, which is what makes the curvature
# visible at all. Wide, slow, Newtonian binaries would satisfy Peters and show
# nothing.
ST_GW_ENABLED = True
# --- Post-Newtonian dynamics (EIH, 1PN) ---------------------------------
# [EIH 1938]  Einstein, Infeld & Hoffmann, Ann. Math. 39, 65: the 1PN N-body
#             equations of motion. Also [Will 1993] eq. 6.80, and Moyer's
#             formulation — the basis of JPL's DE ephemerides (DE440).
#
# The acceleration of body i is Newton plus 1PN corrections in (v/c)^2 and
# (Gm/rc^2): velocity terms, the "many-body" terms where every OTHER mass k
# modifies the i-j interaction (gravity gravitates — this is what makes it GR
# and not a two-body patch), and terms in the other bodies' accelerations.
#
# It is IMPLICIT: a_j appears on the right-hand side. Standard practice is to
# seed with the Newtonian acceleration and iterate a couple of times, which is
# what ST_PN_ITERS does. Two is plenty at our v/c.
ST_PN_ENABLED = True
ST_PN_ITERS = 2
# Where the 1PN series stops being trustworthy. This is not a code limit, it is
# an HONESTY limit: the expansion parameter is (v/c)^2, so at v/c = 0.3 the
# neglected 2PN terms are already ~1%, and by 0.5 the series is not converging
# in any useful sense. Above this the HUD says so rather than pretending.
ST_PN_VC_WARN = 0.3
# Multiplier on the radiated power. 1.0 = TO SCALE, and it stays there.
#
# I expected to need a big number here and was wrong by orders of magnitude — a
# useful thing to have checked rather than assumed. Real inspirals take
# megayears because real binaries are WIDE (v/c ~ 1e-3); this sandbox is not.
# With c = sqrt(2G/RS_PER_MASS) ~ 966 px/s and orbits at ~150 px/s, bodies here
# move at v/c ~ 0.16, a few rs apart — the same strong-field regime as LIGO's
# last second. Peters then gives a merger time of ~1 s of sim time for two Holes
# at 160 px. Nothing needs speeding up; the demo is the real rate.
#
# (An early 4e4 here did not merge things faster, it blew the integrator up: the
# drag scales as P/v^2, so an absurd P reverses the velocity every sub-step and
# the pair flies apart. If a binary ever explodes instead of spiralling, suspect
# this.)
ST_GW_GAIN = 1.0
# Fraction of the total mass radiated away when two horizons merge. ~5% is the
# measured/NR value for comparable-mass black-hole mergers (GW150914 radiated
# 3.0 of 65 Msun). Applied only to hole-hole mergers.
ST_MERGE_GW_MASS_LOSS = 0.05
ST_MERGE_FLASH = 1.0

# --- Space reacting: the radiated wave itself ----------------------------
# The energy the pair loses does not vanish — it leaves as a WAVE, and the grid
# is what it passes through. Same quadrupole formula that sets the loss, so the
# two are automatically consistent: what the binary pays for, the sheet shows.
#
#     h_ij^TT(t, D) = (2G / (c^4 * D)) * Qddot_ij(t - D/c)
#
# with Qddot the trace-free mass quadrupole's second time derivative, evaluated
# at RETARDED time — which is the whole point: the ripple leaves the source and
# arrives late, at exactly c. Nothing is faked; delay, the 1/D amplitude falloff,
# the quadrupolar lobes and the 2x-orbital frequency all fall out of the formula.
#
# Qddot is computed in closed form from the state we already have,
#     Iddot_ij = SUM_a m_a * (2 v_i v_j + x_i a_j + a_i x_j),
# so there is no numerical differentiation and no extra integration cost.
#
# Polarisation: the grid IS the orbital plane, and an in-plane observer sees a
# purely LINEARLY polarised wave (h_x = 0 there) — a real GR result that falls
# out here rather than being imposed. The transverse direction for an in-plane
# ray is z, i.e. out of the sheet, so the wave correctly shows up as a HEIGHT
# ripple and not as an in-plane wobble.
ST_GW_WAVE_ENABLED = True
# How much history to keep (s of sim time). Only needs to cover the light-travel
# time to the far corner: ~1200 px / c ~ 0.65 s here. 2 s is slack for a slow
# sim-speed setting.
ST_GW_HIST_S = 2.0
# Display amplification of the strain, and it is enormous ON PURPOSE. Measured
# h here is ~1e-4 — meaning a 400 px grid line changes length by 0.04 px, which
# is invisible, which is the honest point: gravitational waves are absurdly
# weak. LIGO measures h ~ 1e-21, a proton's width across 4 km, and that is why
# it took a century and a Nobel to see one. This gain (measured: h ~ 5e-4 here
# -> a ~20 px ripple) buys the picture; the
# NUMBER it is amplifying is the real one, and the HUD shows it unamplified.
ST_GW_STRAIN_GAIN = 4.0e4
ST_GW_WAVE_MAX_PX = 60.0     # cap the ripple's height so a merger chirp cannot
                             # tear the sheet apart on screen

# Backdrop dimming. The camera image is darkened UNDER the grid so the thin
# wireframe reads against a bright room — "a bit", not blacked out: the point
# is still a person standing inside a warped spacetime.
#
# IMPORTANT: this is a DISPLAY-only effect and must stay that way. The dim is
# applied by the renderer (browser canvas, or the cv2 fallback's draw()), never
# to the frame handed to inference. See the Spacetime.draw docstring.
ST_BACKDROP_ALPHA = 0.45
ST_BACKDROP_RGB = [6, 8, 18]

# Vtuber / Puppet interactable.
# A friendly cosmic mascot puppeteered by the live landmarks: its paws ride
# the tracked HANDS (always available), its mouth opens with the pinch, and
# — when body pose is on (HALL_POSE=1) — its arms follow shoulder/elbow/wrist.
# Pure rendering happens in the browser (and a cv2 fallback); the backend
# only carries a tiny mode/expression snapshot. `PUPPET_IDLE_BOB_S` is the
# period of the head's resting bob.
PUPPET_IDLE_BOB_S = 3.2

# Schrodinger's cat experiment ("Quantum Cat").
# A four-phase quantum measurement game: drop the cat in the box, fire a
# quantum particle at the box's detector (slingshot pull), watch the box hold
# |alive> + |dead> while nobody looks, pinch it open to collapse the state —
# a fair coin (Born rule), with a persistent alive/dead tally so repeat runs
# visibly converge to 50/50.
#
# There is NO time integration here (the particle flies at constant speed),
# so this scene has none of the fixed-dt discipline the wave/orbit scenes
# need. All geometry below travels to the browser inside to_state() — this
# scene deliberately has NO hand-mirrored constants; the superposition
# ghost-pulse clocks are renderer-local decoration.
SCAT_BOX_CX_FRAC = 0.62       # box centre, fraction of frame width
SCAT_BOX_CY_FRAC = 0.55       # box centre, fraction of frame height
SCAT_BOX_W_FRAC = 0.24        # box width, fraction of frame width
SCAT_BOX_H_FRAC = 0.36        # box height, fraction of frame height
SCAT_CAT_START = (0.28, 0.62)  # cat spawn point, fraction of frame
SCAT_CAT_R_FRAC = 0.055       # cat head radius, fraction of frame height
SCAT_GRAB_PAD_PX = 60         # extra pinch-to-cat reach that starts a drag
# The alpha gun replaces the old slingshot emitter (v1 pinch-pull-release was
# judged unintuitive): a labelled trigger button fires one particle at the
# Geiger tube on the chamber wall — Schrodinger's 1935 apparatus (Geiger
# counter + relay hammer + HCN flask) with the "tiny bit of radioactive
# substance" promoted to a visible gun. Gun placement: muzzle level with the
# Geiger tube (the y comes from the tube) and well inside the frame
# (EDGE_MARGIN_FRAC rule: landmarks degrade near the border).
SCAT_GUN_MUZZLE_X_FRAC = 0.35  # muzzle tip, fraction of frame width
SCAT_GUN_W_FRAC = 0.13        # gun sprite width, fraction of frame width
SCAT_TRIGGER_R_PX = 70        # pinch distance that pulls the trigger
SCAT_RECOIL_DECAY = 0.85      # gun kick + muzzle flash decay per frame
SCAT_PARTICLE_SPEED = 550.0   # px/s, constant, straight at the Geiger tube
SCAT_FRAME_DT = 1.0 / 30.0    # nominal per-frame particle advance (s)
SCAT_DETECTOR_R_PX = 46       # hit radius around the Geiger tube
SCAT_COLLAPSE_P_ALIVE = 0.5   # Born rule for this box: a fair coin
SCAT_FLASH_DECAY = 0.90       # collapse flash decay per frame (1 -> 0)
# Sprite art shared by BOTH renderers (CC0 — web/src/assets/schrodinger/
# CREDITS.md). The cv2 fallback loads the same PNGs the frontend bundles;
# path is repo-root relative like the model paths. Missing files degrade to
# the old vector-drawn cat, so a partial deploy still renders.
SCAT_SPRITE_DIR = "web/src/assets/schrodinger"

# ---------------------------------------------------------------------------
# QR plate: every RUNNING experiment shows a white plate bottom-left with its
# QR code — a link to the experiment's page on the exhibit website
# (docs/ on GitHub Pages; codes rendered by web/scripts/gen_qr.py into
# QR_DIR, one PNG per `session.experiment` key). If a PNG is missing the
# plate degrades to the old dashed "QR" placeholder. Not a pinch target, so
# it may sit closer to the border than EDGE_MARGIN_FRAC allows for
# interactables. Geometry is hand-mirrored — keep in sync with
# web/src/overlay/scene.ts (QR_BOX_FRAC / QR_MARGIN_FRAC beside drawQrPlate).
QR_BOX_FRAC = 0.16     # plate side, fraction of frame height
QR_MARGIN_FRAC = 0.03  # gap to the bottom-left corner, fraction of height
# Same both-renderers path convention as SCAT_SPRITE_DIR (repo-root
# relative): the cv2 path imreads the PNGs the frontend bundles via Vite.
QR_DIR = "web/src/assets/qr"


if __name__ == "__main__":
    print("config file, not supposed to be run directly")