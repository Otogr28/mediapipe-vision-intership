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

# Vtuber / Puppet interactable.
# A friendly cosmic mascot puppeteered by the live landmarks: its paws ride
# the tracked HANDS (always available), its mouth opens with the pinch, and
# — when body pose is on (HALL_POSE=1) — its arms follow shoulder/elbow/wrist.
# Pure rendering happens in the browser (and a cv2 fallback); the backend
# only carries a tiny mode/expression snapshot. `PUPPET_IDLE_BOB_S` is the
# period of the head's resting bob.
PUPPET_IDLE_BOB_S = 3.2


if __name__ == "__main__":
    print("config file, not supposed to be run directly")