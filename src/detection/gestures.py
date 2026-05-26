import math
from collections import deque

from config import PINCH_HISTORY_LEN, PINCH_CLOSE_DROP

PINCH_LANDMARK_A = 4   # thumb tip (hand)
PINCH_LANDMARK_B = 8   # index finger tip (hand)

POSE_SCALE_A = 11      # left shoulder (pose)
POSE_SCALE_B = 12      # right shoulder (pose)
POSE_SCALE_MIN_VISIBILITY = 0.5

# Per-hand history of pinch_dist / pose_scale. Keyed on a stable hand id
# (handedness) so it survives index swaps between frames.
_ratio_history: dict[str, deque[float]] = {}


def hand_id(hand_result, i):
    """Best-effort stable id for the i-th hand in a HandLandmarkerResult.

    Prefers MediaPipe's handedness category ("Left" / "Right") since the
    iteration index can swap between frames. Falls back to the index when
    handedness is unavailable.
    """
    if hand_result and hand_result.handedness and i < len(hand_result.handedness):
        cats = hand_result.handedness[i]
        if cats:
            return cats[0].category_name
    return f"hand_{i}"


def pose_scale(pose_landmarks, frame_w, frame_h):
    """Shoulder-to-shoulder pixel distance from the pose landmarks.

    Used as a depth-invariant size proxy for sizing hand gestures. Unlike
    a hand-based scale, this does not collapse when the user closes their
    fingers (e.g. a fist) — the shoulders stay put regardless of finger
    pose, so the pinch threshold no longer misfires on a closed hand.

    Returns ``0.0`` when either shoulder is missing or below the
    visibility threshold, which callers should treat as "no scale
    available — skip gesture detection".
    """
    if not pose_landmarks:
        return 0.0

    a = pose_landmarks[POSE_SCALE_A]
    b = pose_landmarks[POSE_SCALE_B]

    if a.visibility is not None and a.visibility < POSE_SCALE_MIN_VISIBILITY:
        return 0.0
    if b.visibility is not None and b.visibility < POSE_SCALE_MIN_VISIBILITY:
        return 0.0

    ax, ay = a.x * frame_w, a.y * frame_h
    bx, by = b.x * frame_w, b.y * frame_h
    return math.hypot(ax - bx, ay - by)


def pinch_state(hand_landmarks, pose_landmarks, frame_w, frame_h, ratio,
                hold_ratio=None, hand_id="default",
                a_idx=PINCH_LANDMARK_A, b_idx=PINCH_LANDMARK_B):
    """Detect a thumb-index pinch with a rapid-close requirement and
    optional hysteresis between triggering and holding.

    Returns ``(pinching, held, (mx, my))``:

    * ``pinching`` — True only on the frames where the pinch *gesture* is
      fresh: the fingers are currently closed (ratio below ``ratio``)
      **and** the ratio dropped by at least ``PINCH_CLOSE_DROP`` from its
      peak within the last ``PINCH_HISTORY_LEN`` frames. Use this to
      *trigger* actions (button click, grab initiation). A hand that is
      already closed when it enters the frame will not fire — this
      prevents a fist sliding over a button from registering a click.
    * ``held`` — True whenever the fingers are within ``hold_ratio``
      (defaults to ``ratio`` when omitted). Passing a larger
      ``hold_ratio`` than ``ratio`` introduces **hysteresis**: a gesture
      can be triggered by a tight pinch and then *held* even as the
      fingers drift partially open. Use this to maintain a gesture that
      was already triggered (e.g. keep dragging a grabbed sphere as long
      as the hand stays roughly closed) without making the hold so
      fragile that minor finger drift drops the gesture.
    * ``(mx, my)`` — pixel midpoint of the two pinch landmarks. Always
      provided so callers can use it as a cursor for hover.

    ``hand_id`` keys the per-hand history; pass a stable id (use the
    ``hand_id()`` helper) so tracking survives across frames.
    """
    if hold_ratio is None:
        hold_ratio = ratio

    a = hand_landmarks[a_idx]
    b = hand_landmarks[b_idx]
    ax, ay = a.x * frame_w, a.y * frame_h
    bx, by = b.x * frame_w, b.y * frame_h

    pinch_dist = math.hypot(ax - bx, ay - by)
    midpoint = ((ax + bx) / 2.0, (ay + by) / 2.0)

    scale = pose_scale(pose_landmarks, frame_w, frame_h)
    if scale <= 0:
        return False, False, midpoint

    current_ratio = pinch_dist / scale
    closed_strict = current_ratio < ratio
    held = current_ratio < hold_ratio

    hist = _ratio_history.get(hand_id)
    if hist is None:
        hist = deque(maxlen=PINCH_HISTORY_LEN)
        _ratio_history[hand_id] = hist
    hist.append(current_ratio)

    if not closed_strict or len(hist) < 2:
        return False, held, midpoint

    # Rapid-close check: did the ratio drop sharply within the window?
    # If the hand has been closed the entire window, recent_max is close
    # to current_ratio and no fresh "pinch event" is registered.
    recent_max = max(hist)
    closing_drop = recent_max - current_ratio
    pinching = closing_drop >= PINCH_CLOSE_DROP

    return pinching, held, midpoint
