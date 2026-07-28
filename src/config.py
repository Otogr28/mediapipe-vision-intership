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

# --- Which gesture closes the cursor (HALL_GESTURE) -----------------------
# The pinch above is precise but demanding: it asks a visitor to bring two
# specific fingertips together and hold them there while aiming. Closing the
# whole hand is a bigger, more legible motion — easier to explain in one
# picture, easier for kids, and far more tolerant of landmark noise, which is
# what an exhibit at arm's length actually gets. So the gesture is selectable:
#
#   "pinch"  — thumb-index distance only (the historical behaviour, with the
#              thumb-tip cursor anchor and its counter-movement compensation).
#   "fist"   — finger curl only: the cursor closes when the hand closes.
#   "either" — DEFAULT. Whichever gesture the visitor happens to make closes
#              the cursor. A superset of both, so nobody has to be taught the
#              "right" one before the exhibit responds to them.
#
# `fist`/`either` move the cursor anchor to the palm (see FIST_CURSOR_LANDMARK)
# because the thumb-tip anchor and its compensation are thumb-index-pinch
# machinery: with the whole hand closing there is no single travelling finger
# to cancel, and the palm is the point a visitor reads as "where my hand is".
GESTURE_MODE = os.environ.get("HALL_GESTURE", "either")
if GESTURE_MODE not in ("pinch", "fist", "either"):
    print(f"HALL_GESTURE={GESTURE_MODE!r} is not pinch/fist/either; "
          "falling back to 'either'")
    GESTURE_MODE = "either"

# Finger curl, measured per finger as |tip - wrist| / |MCP - wrist| and
# averaged over index/middle/ring/pinky (the thumb is excluded: it folds
# ACROSS the palm rather than into it, so its own ratio barely moves).
#
# The metric is deliberately a ratio of two wrist-anchored distances rather
# than a length over `hand_scale`: numerator and denominator foreshorten
# together, so it survives a hand tilted toward the camera, and it needs no
# size reference at all. Typical adult values, both hands, any distance:
#   ~1.85  fingers straight out
#   ~1.6   the relaxed pose a hand rests in when held up at a screen
#   ~1.2   a claw, fingers well curled but not closed
#   ~0.7   deliberate fist, tips folded past the knuckles into the palm
# The last part of the curl is what drops the ratio steeply — the fingertip
# folds BACK past its own knuckle, so the numerator falls below the
# denominator — which is what leaves a fist so far from every partial pose.
# Hence: close low enough that only a real fist reaches it, release low
# enough that uncurling half-way lets go (a visitor should not have to
# splay their fingers to put an object down).
# Run with HALL_DEBUG=1 to watch the live value (the HUD prints both the
# pinch and the fist ratio per hand) before changing these.
FIST_CLOSE_RATIO = 1.05
FIST_RELEASE_RATIO = 1.30

# The cursor anchor in fist/either mode: landmark 9, the middle finger's
# knuckle. It is the centre of the palm polygon, the fingers cannot move it,
# and it is where a visitor points at a target with a closed hand.
FIST_CURSOR_LANDMARK = 9

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

# 6 7 Counter. Counts each time a HAND completes an up-stroke: it drops,
# then rises again by at least `SIXSEVEN_PUMP_AMP` of its own width. Hands
# latch independently, so the alternating two-handed gesture scores twice
# per cycle and one hand alone still scores.
#
# The original 67counter definition — "wrist rises above elbow" — was
# measured on the exhibit and scored two counts, then silence. People do 6-7
# with their elbows down by the waist and their hands alternating at chest
# height, so the wrist starts above the elbow and never drops back below it;
# the latch fired once per arm and could never re-arm. Judging a hand
# against where that same hand just was carries no posture assumption, and
# it drops the body model entirely (no ~1.5 CPU cores, and no multi-second
# TensorRT engine build inside the render loop when a visitor opens the
# game).
#
# The unit is the hand's OWN width (`gestures.hand_scale`), which is what
# makes one constant cover the whole room: a hand twice as far away is half
# as wide on screen and its stroke is half as many pixels, so the same
# physical gesture counts at any distance with no depth estimate. ~0.9 hand
# widths is roughly 7 cm of travel for an adult, well inside a real pump
# (15-25 cm) and well outside landmark jitter. Raise it if idle hand-waving
# scores; lower it if small gestures are ignored.
SIXSEVEN_PUMP_AMP = 0.9
# A hand gone longer than this starts its latch over rather than inheriting
# the old trough — it may come back somewhere unrelated, and that would
# score a count the visitor never made.
SIXSEVEN_HAND_GRACE_S = 0.4
# Frames over which the count-flash animation decays back to 0.
SIXSEVEN_FLASH_FRAMES = 12

# The counter is played as a TIMED ROUND, and the round is what makes the
# scoreboard mean anything: an unbounded tally rewards whoever stands in
# front of the camera longest, so the "record" would just be the longest
# visit. A fixed window turns it into a rate, which is a real contest.
# The round starts on the first count (no button — the exhibit is
# touchless and the gesture the player already made is the best trigger),
# so the clock only ever measures time spent actually pumping.
SIXSEVEN_ROUND_S = 30.0
# How long the final score + board stay up before the counter re-arms for
# the next player. Long enough to read five rows and point at your own.
SIXSEVEN_OVER_S = 8.0
SIXSEVEN_BOARD_SIZE = 5      # rows kept on the high-score table
# Where those records live. OUTSIDE the repo on purpose: the Jetson
# updates itself with `git reset --hard` (see deploy/hall-app), which
# would wipe any file tracked here, and the scores are the one piece of
# exhibit state that should survive both an update and a reboot.
SIXSEVEN_SCORES_FILE = os.path.expanduser(
    os.environ.get("HALL_SCORES_FILE", "~/hall-scores.json"))

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

# Which gesture the animated demo hands act out, and the words next to them.
# "either" teaches the FIST: it is the bigger, simpler motion, it reads from
# across a hall, and a visitor who pinches instead still works — so teaching
# the easier of two accepted gestures costs nothing. Both renderers read
# these (ui/hints.py, ui/attract.py, and `session.gesture` in the browser).
DEMO_GESTURE = "pinch" if GESTURE_MODE == "pinch" else "fist"
HINT_TEXT = ("Pinch your fingers to interact" if DEMO_GESTURE == "pinch"
             else "Close your hand to interact")

# ---------------------------------------------------------------------------
# Attract mode: the exhibit when nobody is standing in front of it.
#
# A hall exhibit spends most of its day alone. Left to itself the app showed a
# live camera feed of an empty corridor with a menu floating over it, stuck in
# whatever scene the last visitor abandoned. Attract mode gives it the two
# states a museum display is supposed to have:
#
#   ATTRACT   nobody near — a full-screen slideshow of the experiments, the
#             way any other display in the building behaves. The camera feed
#             is covered (an empty room is not interesting, and not filming
#             the corridor at people who never opted in is the polite default).
#   GREETING  somebody just walked up — a short "Hi" plus one animated demo of
#             the gesture that drives everything, then the live menu. The point
#             is that a visitor learns the control before they need it, the way
#             a console game shows the controller motion before the first level.
#
# Leaving resets the app to the menu, so the next visitor never inherits the
# last one's half-finished black hole.
#
# HALL_ATTRACT=0 disables the whole thing (the app is always live, which is
# what you want on a laptop while developing).
ATTRACT_ENABLED = os.environ.get("HALL_ATTRACT", "1") == "1"

# Seconds of continuous absence before the exhibit goes back to the slideshow.
# Long enough to survive a visitor stepping out of frame to fetch a friend,
# short enough that the display is not left mid-experiment for the next one.
ATTRACT_IDLE_S = 30.0

# Seconds per slide, and the cross-fade between them.
ATTRACT_SLIDE_S = 6.5
ATTRACT_FADE_S = 1.2

# Slideshow source, in priority order.
#
# ATTRACT_GALLERY_DIR is a plain folder of photographs OUTSIDE the repo: on
# the exhibit machine, dropping a .jpg in there puts it in the rotation, and
# deleting one takes it out. Nothing to edit, nothing to commit, nothing to
# rebuild — which is the whole point, since whoever refreshes the photos in
# the hall is not going to be editing Python. `deploy/hall-app/push-photos.sh`
# fills it from a folder on the laptop.
#
# The gallery is deliberately not in git: it holds photographs of people, and
# this repository is public. That also means a fresh checkout has none, so
# ATTRACT_DIR (the eight experiment stills the exhibit website already uses)
# is the fallback whenever the gallery is missing or empty — a laptop running
# the app still gets a slideshow instead of a black screen.
ATTRACT_GALLERY_DIR = os.path.expanduser(
    os.environ.get("HALL_ATTRACT_DIR", "~/hall-photos"))
ATTRACT_DIR = "docs/img"

# How often the slideshow re-reads its directory. Adding a photograph to the
# gallery should not need a restart of a machine that lives behind a plinth,
# so the list is rescanned while the exhibit is idle; a new file joins the
# rotation within a minute of being copied in.
ATTRACT_RESCAN_S = 60.0

# Above this many slides the position dots become a smear, so the renderers
# switch to a plain "12 / 82" counter. A gallery folder crosses this the
# moment somebody empties a phone into it; the eight experiment stills do not.
# Keep in sync with MAX_DOTS in web/src/hud/Attract.tsx (the browser renderer).
ATTRACT_MAX_DOTS = 12

# Title + one-line caption per slide, keyed by the image stem (which is also
# the `session.experiment` key, so a slide and its QR page always agree).
ATTRACT_SLIDE_TEXT = {
    "black_hole": ("Black Hole",
                   "Light bends around a mass so dense it has no surface"),
    "slingshot": ("Slingshot",
                  "Pull, aim, release — gravity and drag do the rest"),
    "orbitals": ("Orbitals",
                 "Launch worlds and watch gravity pull them into orbit"),
    "waves": ("Waves",
              "Drop sources in a ripple tank and interfere them"),
    "charges": ("Charges",
                "Place charges and see the electric field they make"),
    "magnets": ("Magnets",
                "Move a magnet through a coil and light a bulb"),
    "spacetime": ("Spacetime",
                  "Mass curves the sheet that everything else falls along"),
    "schrodinger": ("Quantum Cat",
                    "Measure the atom and the cat stops being both"),
}

# Greeting: how long the "Hi" + gesture demo holds before the menu appears.
# A visitor who makes the gesture during it skips straight through — trying
# the control is a better exit than waiting out a timer.
GREETING_S = 5.0
GREETING_TITLE = "Hi"
GREETING_SUBTITLE = "This display is controlled with your hand"

# The line under the slideshow. It is the only thing telling somebody walking
# past that the screen is not a poster, so it says what to do, not what the
# exhibit is.
ATTRACT_PROMPT = "Step closer to control this display with your hand"
ATTRACT_TITLE = "Physics and Engineering Life"

# ---------------------------------------------------------------------------
# Presence: is somebody standing CLOSE TO the exhibit?
#
# "Close" is the operative word. The exhibit is armed for somebody within
# reach of it, not for the corridor traffic behind them: waking up for every
# person who walks past means the slideshow is never on screen, the app
# resets itself under whoever is actually using it, and the greeting plays to
# an empty room. So each of the three signals below carries its own SIZE gate,
# and size is the distance estimate — a fixed camera has no depth, but
# everything gets bigger as it comes closer, which is enough.
#
#   1. A tracked HAND, big enough in frame. Free (the hand detector runs every
#      frame anyway) and unambiguous: a hand you can measure is a hand within
#      arm's reach of the screen.
#   2. Frame MOTION against a slowly-learned background — the signal that
#      catches somebody walking up with their hands down, which is how people
#      actually approach a display. Costs ~0.2 ms/frame: the frame is reduced
#      to a PRESENCE_GRID_W-wide grayscale thumbnail first.
#   3. A detected POSE, when some other feature already has pose running.
#      Never turned on for presence alone — body inference is the app's
#      biggest CPU cost and motion answers the same question for free.
#
# The background is an EMA that only adapts while nobody is present, so a
# visitor who walks up and then stands perfectly still keeps registering
# instead of being absorbed into the background after a few seconds.
PRESENCE_GRID_W = 64            # thumbnail width in px (height keeps aspect)
PRESENCE_PIXEL_DELTA = 18       # per-pixel gray difference counted as "changed"

# --- motion ---
# The changed pixels are grouped into blobs and only the LARGEST one is
# judged, on two counts: how much of the frame it covers, and how TALL it is.
# Height is what separates near from far. A person at the screen runs from the
# bottom edge to near the top; the same person four metres back is a short
# patch high in the frame no matter how briskly they move, and a scatter of
# small changes (a flickering lamp, a screen behind, leaves outside a window)
# never forms one tall blob at all. A bare changed-pixel fraction, which is
# what this used to be, cannot tell those apart.
PRESENCE_ENTER_FRAC = 0.14      # blob area, as a fraction of the frame
PRESENCE_ENTER_SPAN = 0.55      # blob height, as a fraction of frame height
# Looser thresholds to STAY present. Hysteresis, so somebody standing at the
# exhibit does not drop out every time they lean back.
PRESENCE_EXIT_FRAC = 0.06
PRESENCE_EXIT_SPAN = 0.35

# --- hand ---
# Longest side of the hand's bounding box, as a fraction of the frame. A hand
# held out at the screen measures ~0.2-0.35 of frame height at 720p; the same
# hand three metres away measures under 0.08. Everything the UI does needs the
# hand near the camera anyway, so this gate costs a real visitor nothing.
PRESENCE_HAND_SPAN = 0.16
PRESENCE_HAND_EXIT_SPAN = 0.10

# --- pose ---
# Height of the visible pose landmarks' bounding box. Only consulted when some
# other feature already pays for body inference (HALL_POSE=1, or the Vtuber).
PRESENCE_POSE_SPAN = 0.45
PRESENCE_POSE_EXIT_SPAN = 0.30

# The enter thresholds must hold this long before presence is asserted, so a
# door swinging or a light switching does not wake the exhibit.
PRESENCE_ENTER_S = 0.6

# ---------------------------------------------------------------------------
# Gallery (`ui/gallery.py`) — the third menu entry, next to Games and
# Experiments. It browses the SAME folder the idle slideshow reads
# (ATTRACT_GALLERY_DIR), so there is one place to put photographs and two ways
# to see them: unattended as a slideshow, on demand as something you flip
# through with your hand.
#
# The interaction is the app's existing "close your hand and drag" vocabulary
# applied to a strip of cards — grab anywhere, pull sideways, let go and it
# settles on the nearest photograph. Prev/Next buttons sit under it for
# whoever does not discover the drag; the button press and the drag cannot
# both fire, because a hand over a live button is reserved (see
# `gestures.reserve_hand`).

# Cards, not full-bleed photographs. Two reasons, both about the visitor:
# the neighbours peeking in at either edge are what say "there are more, and
# they move sideways" without a word of instruction, and leaving the camera
# visible around the card keeps them looking at themselves, which is the only
# feedback that says the screen is tracking their hand.
GALLERY_CARD_H_FRAC = 0.60      # card height, fraction of the frame
GALLERY_CARD_ASPECT = 16 / 9    # card width / height
GALLERY_GAP_FRAC = 0.035        # gap between cards, fraction of frame WIDTH
# Top of the card. High rather than centred: the column underneath has to
# hold the caption, the counter and the Prev/Next row, and EDGE_MARGIN_FRAC
# already claims the bottom tenth of the frame for those buttons.
GALLERY_CARD_TOP_FRAC = 0.10

# Hand travel that advances one photograph, as a fraction of frame width.
# Deliberately well under 1: EDGE_MARGIN_FRAC exists because the landmark
# model degrades near the border, so a gesture that needs a full-width sweep
# dies half way. A quarter of the frame is a comfortable forearm movement
# from anywhere a hand is likely to start.
GALLERY_DRAG_FRAC = 0.25

# Release faster than this (photographs per second) advances a whole card even
# if the drag never reached the halfway point — the flick everybody already
# expects from a phone.
GALLERY_FLICK_V = 1.8

# Exponential approach rate (1/s) back to the settled photograph after a
# release. High enough to feel like a snap, low enough to read as motion so
# the visitor sees WHICH way it went.
GALLERY_SNAP_RATE = 9.0

# Neighbours either side kept in the state payload. 2 covers the card peeking
# in at each edge plus one more for a fast flick; the folder can hold any
# number of photographs and the payload must not scale with it.
GALLERY_WINDOW = 2
# Background EMA time constant (s) while nobody is present. Long enough to
# ignore a passing cloud, short enough to relearn a moved chair.
PRESENCE_BG_TAU_S = 12.0
# Warm-up after the detector starts: the background is learned FAST and the
# motion signal is ignored. The first frame out of a camera is often garbage
# (a black or half-exposed frame); seeded as the background it would make
# every later frame look like motion, and the exhibit would greet an empty
# room and then sit live for ATTRACT_IDLE_S with nobody there. Hands and
# pose are exempt — those are unambiguous whenever they appear.
PRESENCE_WARMUP_S = 2.0

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

# --- Magnets experiment (magnetostatics + induction) ---------------------
# Pinch empty space to drop a bar magnet of the palette's orientation;
# pinch a bar to drag it. A fixed pickup coil with a light bulb and a
# galvanometer sits in the frame: moving a magnet changes the flux through
# the coil and the induced current lights the bulb (Faraday's law), with
# the deflection flipping sign on reversal (Lenz's law). A magnet held
# still induces nothing, because only dPhi/dt matters. That is the lesson.
#
# FIELD model: exact 2D magnetostatics rather than a point dipole. Each bar
# is a uniformly magnetized rectangle whose H field is that of its two pole
# faces treated as "magnetic surface charge" segments; that has a closed
# form (atan2 + log, the same integral as a charged rod in 2D). Inside the
# bar the bound-magnetization term +M is added back (B = H + M, mu0 = 1),
# so div B = 0 everywhere and field lines close S->N through the bar. Far
# from the bar this converges to the 2D dipole (checked to <0.5% beyond
# ~8 half-lengths); near and inside the bar, where visitors actually look,
# it stays exact, which is precisely what the point-dipole shortcut gets
# wrong. The browser evaluates it per needle cell in a single-pass shader
# (web/src/gl/magnets.frag.glsl); the cv2 fallback vectorizes the same
# closed form in numpy. Keep the two in sync with this block.
#
# INDUCTION model: PhET's faradays-electromagnetic-lab approach. Bx is
# sampled on MAG_COIL_SAMPLES rows across the coil's vertical diameter,
# single-loop flux = sum(Bx * chord * dy) (the chord is the loop's depth at
# that row), EMF = -loops * dPhi/dt between frames, displayed current =
# tanh(EMF / MAG_EMF_REF) with a short exponential smoothing so one noisy
# frame cannot strobe the bulb. Python owns the magnet list AND the
# flux/EMF computation; both renderers only draw what to_state() reports.
MAG_MAX = 4                  # hard cap; also the shader's uniform array size
                             # — keep web/src/gl/magnets.frag.glsl in sync
MAG_GRAB_PAD_PX = 60         # pinch-grab radius around a bar's centre
MAG_HALF_LEN_PX = 70.0       # bar half-length a (pole faces at x = +/- a)
MAG_HALF_H_PX = 22.0         # bar half-height b
# Palette: which way the bar is magnetized. m is the magnetization along +x;
# the N pole is the face the field EXITS (x = +a when m > 0), so the label
# reads left-to-right across the bar.
MAG_TYPES = {
    "sn": {"m": 1.0, "label": "S-N"},
    "ns": {"m": -1.0, "label": "N-S"},
}
MAG_DEFAULT_KIND = "sn"
# Smoothing width (px) of the inside-the-bar +M term. Without it the flux
# jumps discontinuously the instant a pole face crosses a coil sample row,
# and dPhi/dt then spikes with the step phase instead of the physics
# (PhET's transitionSmoothingScale exists for exactly this).
MAG_EDGE_SMOOTH_PX = 12.0
# |B| that maps to a fully opaque compass needle, alpha = tanh(|B|/ref).
# 0.03 saturates the needles within ~150 px of a unit bar and lets the far
# field fade out instead of cluttering the frame.
MAG_B_REF = 0.03
MAG_NEEDLE_SPACING_PX = 38.0  # needle grid cell (px)
MAG_NEEDLE_LEN_PX = 26.0      # needle length; < spacing so cells read apart
# Pickup coil (fixed). Its plane is vertical, so the flux through it is the
# Bx component. Kept inside EDGE_MARGIN_FRAC like every pinch target: the
# coil itself is never grabbed, but magnets get dragged INTO it and the
# hand doing that must stay fully in frame.
MAG_COIL_X_FRAC = 0.70
MAG_COIL_Y_FRAC = 0.52
MAG_COIL_R_PX = 95.0
MAG_COIL_LOOPS = 3
MAG_COIL_SAMPLES = 9          # flux sample rows across the vertical diameter
# EMF that maps to full displayed current, cur = tanh(EMF/ref). Measured on
# this geometry: a 300 px/s head-on approach peaks ~1.4k, a 600 px/s pass
# alongside the coil ~14k, and shoving the bar THROUGH the coil saturates,
# as it physically should (B inside the bar dwarfs the outside field).
MAG_EMF_REF = 8000.0
MAG_CUR_SMOOTH_S = 0.12       # display smoothing time constant (s)
# Real-unit readout under the galvanometer. The mapping is a DECLARED
# physical calibration, then everything downstream is computed honestly:
# the drawn bar (140 x 44 px) is declared a 7 x 2.2 cm ferrite bar magnet,
# so 1 px = 0.5 mm; the model's field just outside the pole face is 0.368
# screen units, declared to be 50 mT (typical ferrite). One screen flux
# unit is then MAG_B_UNIT_T * MAG_PX_TO_M^2 = 3.40e-8 Wb, and since dt is
# real seconds the same factor turns screen EMF into volts. The circuit is
# the drawn one: 3 turns of 1.3 mm copper (~0.9 m, ~12 mOhm) plus the
# meter shunt, rounded to 0.02 ohm. The resulting numbers are the true
# physics of this hardware — a hand-speed pass beside the coil peaks near
# 0.5 mV / 25 mA, shoving the bar through the coil reaches ~10 mV / 0.5 A.
# Real classroom induction coils use hundreds of turns for exactly this
# reason. Mirrored in web/scripts/mock_backend.py's fake values.
MAG_PX_TO_M = 5.0e-4          # 140 px bar = 7 cm
MAG_B_UNIT_T = 0.136          # 50 mT at the pole face / 0.368 screen units
MAG_EMF_TO_V = MAG_B_UNIT_T * MAG_PX_TO_M * MAG_PX_TO_M   # 3.40e-8 V/unit
MAG_CIRCUIT_OHM = 0.02        # coil copper + meter shunt

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
ST_LATTICE_MARGIN = 1.55     # slightly larger than the VISIBLE patch at the
                             # zoomed-out default (1/ST_ZOOM_DEFAULT = 1.33x
                             # the frame), so a mass placed anywhere the user
                             # can reach is INSIDE the volume and the box edges
                             # sit just off-screen — the reference is a
                             # standalone model that can show its own corners;
                             # an AR overlay reads better as "space fills the
                             # view".
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
# default one: the sheet is a finite patch, so a spin must not swing a bare
# corner into view. 1.7 covered a full spin at zoom 1.0; the camera now opens
# at ST_ZOOM_DEFAULT = 0.75 (the view is 1/0.75 = 1.33x the frame each way),
# so the extent scales by the same factor. Cols/rows deliberately do NOT
# scale with it: the world cells get coarser by exactly what the zoom-out
# shrinks them, so on-screen cell density — and the per-frame polyline cost
# the Jetson pays in Canvas2D — is unchanged.
ST_GRID_MARGIN = 2.3

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
# The camera opens ZOOMED OUT. At 1.0 the visible patch is exactly the frame,
# which reads as a close-up of a single well; 0.75 shows ~1.33x the frame each
# way, so a staged system (see the preset block below) has empty space around
# it and a whole binary orbit fits on screen with room to breathe. Placement
# is untouched — the hand still maps to frame px, so the reachable region is
# the middle of the visible space — and the two-hand pinch-zoom can always
# come back to 1.0 and past it.
ST_ZOOM_DEFAULT = 0.75
ST_ZOOM_MIN, ST_ZOOM_MAX = 0.45, 2.4

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
# off-screen mass would keep pulling the scene with no visible cause. 2.4 is
# just past the drawn sheet (ST_GRID_MARGIN 2.3) and matches the widest view
# (min zoom 0.45 shows ~2.2x the frame), so a body vanishes only once no
# camera setting could still show it. A grabbed mass is never pruned.
ST_PRUNE_MARGIN = 2.4
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

# --- Preset systems (one button = one staged scene) -----------------------
# PRECESS proved the pattern: one press stages a system that would take a
# visitor several precise pinches to build. BINARY is the LIGO story end to
# end — two equal Holes on a mutual circular orbit about their COM, spiralling
# in by the GW drag below until the horizons touch and merge (flash, ~5% mass
# radiated, ripples on the sheet the whole way). SYSTEM is the Kepler picture:
# one Sun with three planets on staggered eccentric orbits whose ellipses
# visibly precess. Sizes are fractions of the frame HEIGHT (the binding screen
# dimension), so window mode stages the same picture at any capture size.
ST_BINARY_SEP_FRAC = 0.28    # ~200 px at 720p. Peters gives ~1 min of 1x sim
                             # time to merger — slow enough to watch the orbit
                             # tighten, and the speed buttons cover the
                             # impatient. v/c ~ 0.11 per body at the start, so
                             # the inspiral begins inside the honest 1PN band.
# SYSTEM's planets launch milder and LIGHTER than the hand-placed ORBITER,
# because three of them have to share one screen for minutes. Both numbers
# were sized by measurement, not by the Newtonian back-of-envelope (which
# failed twice here):
#
#   * vfrac 0.92 -> e ~ 0.11: still a visibly precessing ellipse, but the
#     periapsis sits at ~0.78 * apoapsis instead of the ORBITER 0.72's ~0.35,
#     which is what lets three NON-CROSSING orbits fit between the Sun's
#     surface and the frame. The first cut reused 0.72 with evenly spaced
#     radii: the orbits crossed, and a planet-planet encounter walked the
#     middle planet's periapsis into the Sun's 50 px surface within laps.
#   * mass 0.002 vs ST_ORBITER_MASS's 0.02: three 2%-of-the-star planets at
#     screen-sized spacings are a genuinely unstable system — mutual-Hill
#     spacing K ~ 2.4 where long-term stability wants >~ 4 — and the measured
#     result was planet-planet scattering at ~160 s that ended with the star
#     eating its own system. 0.4% (K ~ 4) still lost a planet at ~24 min of
#     sim time; 0.2% (K ~ 5) ran a 30-minute soak clean. The planets still
#     gravitate back; they are just no longer a trio of super-Jupiters.
ST_SYSTEM_SPAWN_VFRAC = 0.92
ST_SYSTEM_PLANET_MASS = 0.002
# Planet apoapses, as fractions of H. Consecutive ratios keep each planet's
# periapsis OUTSIDE its inner neighbour's apoapsis with a REAL gap (>= 55 px
# — the first cut left 1-2 px gaps, which is crossing in all but name): no
# encounters, no scattering. The inner periapsis (~112 px) clears the Sun's
# 50 px surface more than twice over; the outermost apoapsis (~460 px)
# deliberately pokes past the frame's top and bottom — the camera opens
# zoomed out (ST_ZOOM_DEFAULT shows ~480 px of world half-height), so it
# stays fully visible, and planets are not pinch targets (only masses are
# grabbable).
ST_SYSTEM_ORBIT_FRACS = (0.20, 0.36, 0.64)

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