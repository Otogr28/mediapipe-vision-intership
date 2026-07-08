"""Per-frame UI/gesture state serialization for the web frontend.

``build_state()`` assembles ONE compact JSON document per rendered frame —
the complete contract between the Python backend (authoritative for the
state machine, hit-testing and physics) and the browser (a pure renderer).
The document is pushed to clients by ``output.WebSink`` over the ``/state``
SSE endpoint; the schema is mirrored in ``web/src/state/types.ts``.

Conventions:

* Scene geometry (cursors, rects, object positions) is in FRAME PIXELS —
  the backend's native space; the browser scales the whole stage with CSS.
* Landmarks (pose + hands) stay NORMALIZED [0, 1] like MediaPipe emits them.
* Floats are rounded (px 1 dp, normalized 4 dp, physics 3 dp) and the JSON
  uses compact separators, keeping the worst-case payload ~5 KB at 30 Hz.

Imports only stdlib + existing modules; no third-party dependencies (this
must run on the Jetson's system Python 3.10).
"""

import json
import time

from config import (DEBUG_HUD, HALL_INFERENCE, PINCH_CLOSE_RATIO,
                    PINCH_RELEASE_RATIO)
from detection import detectors, gestures

_seq = 0

# EMA of the interval between build_state calls (one per rendered frame)
# -> the render-loop FPS for the debug block, mirroring DebugHUD.
_last_t = None
_dt_ema = 0.0


def _round_pt(pt, ndigits=1):
    return [round(pt[0], ndigits), round(pt[1], ndigits)]


def _hands_state(hand_result, now):
    """Per-hand pinch snapshot + raw landmarks, keyed by stable hand id.

    Machines inside the tracking-grace window (hand momentarily lost) are
    still included — with their last landmarks missing — so the browser can
    apply the same staleness rule as the cv2 cursor (hide past ``seen_ms``).
    """
    landmarks_by_id = {}
    world_by_id = {}
    handed_by_id = {}
    if hand_result is not None:
        # Metric 3D hand skeleton + handedness — present on BOTH backends
        # (MediaPipe HandLandmarker and the GPU shim in gpu_hands.py), but both
        # can emit shorter/empty lists, so index defensively.
        world = getattr(hand_result, "hand_world_landmarks", None) or []
        handed = getattr(hand_result, "handedness", None) or []
        for i, lms in enumerate(hand_result.hand_landmarks):
            hid = gestures.hand_id(hand_result, i)
            landmarks_by_id[hid] = [
                [round(lm.x, 4), round(lm.y, 4)] for lm in lms
            ]
            if i < len(world) and world[i]:
                world_by_id[hid] = [
                    [round(w.x, 4), round(w.y, 4), round(w.z, 4)]
                    for w in world[i]
                ]
            if i < len(handed) and handed[i]:
                handed_by_id[hid] = handed[i][0].category_name

    hands = []
    for hid, m in gestures.pinch_infos():
        hands.append({
            "id": hid,
            "cursor": _round_pt(m.cursor),
            "press_cursor": _round_pt(m.press_cursor),
            "state": m.state,
            "progress": round(m.progress, 3),
            "ratio": round(m.ratio, 3) if m.ratio is not None else None,
            "pinching": m.pinching,
            "held": m.closed,
            "seen_ms": round((now - m.last_seen) * 1000.0, 1),
            "landmarks": landmarks_by_id.get(hid),
            # 3D hand skeleton (meters, wrist origin) + raw handedness — drive
            # the vtuber's hand orientation + fingers. None during grace window.
            "world": world_by_id.get(hid),
            "handedness": handed_by_id.get(hid),
        })
    return hands


def _pose_state(pose_landmarks):
    if pose_landmarks is None:
        return None
    return [
        [round(lm.x, 4), round(lm.y, 4),
         round(lm.visibility, 2) if lm.visibility is not None else 1.0]
        for lm in pose_landmarks
    ]


def _pose_world_state(pose_world_landmarks):
    """Metric 3D skeleton (meters, origin at the hips midpoint) as 33 [x, y, z].

    This is MediaPipe's ``pose_world_landmarks`` — a gravity-aligned, camera-
    independent 3D pose, unlike the weak per-image ``z`` of ``_pose_state``.
    Visibility is NOT repeated here; the rig reuses ``pose[i][2]`` (same
    indices) to gate a joint. 3 dp is ~1 mm precision, plenty for rigging.
    """
    if pose_world_landmarks is None:
        return None
    return [
        [round(lm.x, 3), round(lm.y, 3), round(lm.z, 3)]
        for lm in pose_world_landmarks
    ]


def _debug_state(render_fps):
    return {
        "render_fps": round(render_fps, 1),
        "hand_fps": round(detectors.hand_fps(), 1),
        "pose_fps": round(detectors.pose_fps(), 1),
        "age_ms": round(gestures.result_age_s() * 1000.0, 1),
        "backend": HALL_INFERENCE,
        "close_ratio": PINCH_CLOSE_RATIO,
        "release_ratio": PINCH_RELEASE_RATIO,
    }


def build_state(ui, hand_result, pose_landmarks, pose_world_landmarks=None):
    """One frame's complete UI state as compact JSON bytes (UTF-8).

    Call once per rendered frame, after ``ui.update(...)`` (the pinch
    snapshot must be advanced) — ``main.py`` hands the result straight to
    ``sink.publish_state``. ``pose_world_landmarks`` is optional: the 2D
    ``pose`` still drives the skeleton overlay + head; the 3D ``pose_world``
    (when present) drives the vtuber rig's per-bone orientation.
    """
    global _seq, _last_t, _dt_ema
    now = time.monotonic()
    if _last_t is not None:
        dt = now - _last_t
        _dt_ema = dt if _dt_ema == 0.0 else 0.9 * _dt_ema + 0.1 * dt
    _last_t = now
    _seq += 1

    state = {
        "seq": _seq,
        "t": round(now, 3),
        "frame": {"w": ui.frame_w, "h": ui.frame_h},
        "hands": _hands_state(hand_result, now),
        "pose": _pose_state(pose_landmarks),
        "pose_world": _pose_world_state(pose_world_landmarks),
        "debug": (_debug_state(1.0 / _dt_ema if _dt_ema > 0.0 else 0.0)
                  if DEBUG_HUD else None),
    }
    state.update(ui.to_state())
    return json.dumps(state, separators=(",", ":")).encode("utf-8")
