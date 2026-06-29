import os

import mediapipe as mp

POSE_MODEL_PATH = "models/pose_landmarker_lite.task"
HAND_MODEL_PATH = "models/hand_landmarker.task"
IMAGE_FORMAT = mp.ImageFormat.SRGB

# Camera source. Either a local device index ("0") or a stream URL — e.g. an
# MJPEG feed from another machine ("http://<ip>:8091/stream.mjpg") so this node
# can infer on a *remote* camera (the Jetson pulling a laptop's webcam). Set
# with the HALL_CAMERA env var; defaults to the first local device.
SELECTED_CAMERA = os.environ.get("HALL_CAMERA", "0")

# Where the annotated output goes (HALL_OUTPUT):
#   "window" — an on-screen cv2 window (needs a display); press 'q' to quit.
#   "stream" — a headless MJPEG HTTP server, viewable in a remote browser.
#              Used on the Jetson when driving it from a laptop (no monitor).
OUTPUT_MODE = os.environ.get("HALL_OUTPUT", "window")
# MJPEG server settings for OUTPUT_MODE == "stream":
STREAM_BIND = os.environ.get("HALL_STREAM_BIND", "auto")    # "auto" -> Tailscale IP
STREAM_PORT = int(os.environ.get("HALL_STREAM_PORT", "8092"))
STREAM_QUALITY = int(os.environ.get("HALL_STREAM_QUALITY", "80"))  # JPEG 1..100

# Requested capture resolution for the webcam. The actual frame size is read
# back after `cv2.VideoCapture.set(...)` because some drivers silently snap
# to the nearest supported mode. The cv2 display window inherits this size.
WINDOW_WIDTH = 1920
WINDOW_HEIGHT = 1080

NUM_POSES = 1
MIN_POSE_DETECTION_CONFIDENCE = 0.5
MIN_POSE_PRESENCE_CONFIDENCE = 0.5
MIN_POSE_TRACKING_CONFIDENCE = 0.5

NUM_HANDS = 2
MIN_HAND_DETECTION_CONFIDENCE = 0.5
MIN_HAND_PRESENCE_CONFIDENCE = 0.5
MIN_HAND_TRACKING_CONFIDENCE = 0.5

# Gesture detection
# Pinch fires when distance(thumb_tip, index_tip) < PINCH_RATIO * pose_scale,
# where pose_scale is the shoulder-to-shoulder pixel distance from the pose
# landmarks. A ratio (not pixels) keeps detection consistent at any camera
# distance; using the pose for scale instead of the hand prevents a closed
# fist from collapsing the reference and misfiring as a pinch.
PINCH_RATIO = 0.09

# Hysteresis: once a gesture is *triggered* by a tight pinch (PINCH_RATIO),
# it is *held* as long as the ratio stays below PINCH_HOLD_RATIO. Making the
# hold threshold looser than the trigger threshold means a grabbed object
# stays grabbed even when the user's fingers drift a bit open — only a
# clear release motion drops the gesture. Use the same value as PINCH_RATIO
# to disable hysteresis entirely.
PINCH_HOLD_RATIO = 0.25

# Rapid-close requirement: a pinch only fires when, in addition to being
# currently closed, the ratio (pinch_dist / pose_scale) dropped by at least
# PINCH_CLOSE_DROP from its peak within the last PINCH_HISTORY_LEN frames.
# This stops a hand that is already closed (e.g. a fist passing over a
# button) from registering a phantom pinch — the gesture must include an
# actual closing motion, not just a closed shape.
PINCH_HISTORY_LEN = 10
PINCH_CLOSE_DROP = 0.15

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