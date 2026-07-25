"""Exercise the closing-gesture pipeline (HALL_GESTURE) on a synthetic hand.

    uv run python tests/smoke_gestures.py

Why this exists: `detection/gestures.py` now drives one state machine from
either a thumb-index pinch or a whole-hand fist, and the mode is read from the
environment at import time. Nothing else in the repo can catch a mode that
never fires, fires on the wrong pose, or crashes on a degenerate hand — the
app just silently stops responding to visitors, which on the kiosk looks
exactly like a camera fault.

So: build a 21-landmark hand from an articulated finger model, pose it four
ways, and assert which poses close the cursor in each of the three modes.

WHAT THIS DOES NOT DO: validate the thresholds themselves. The hand model is
anatomy on paper, not a person in front of the exhibit's camera. It pins the
SEMANTICS (fist mode reacts to a fist and not to a pinch, and so on) and the
rough ratio scale; FIST_CLOSE_RATIO / FIST_RELEASE_RATIO still want a pass
with HALL_DEBUG=1 against real hands at the exhibit's working distance. The
ratio table printed at the end is the reference for that pass.

Deliberately plain `python` with no pytest dependency, like smoke_scenes.py:
this must also run on the Jetson's system Python 3.10.
"""

import importlib
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

W, H = 1280, 720

# --- synthetic hand -------------------------------------------------------
# Hand-space units: wrist at the origin, +y toward the fingertips. Roughly an
# adult hand normalized so the middle knuckle sits 0.38 from the wrist.

_MCP = {"index": (0.10, 0.36), "middle": (0.02, 0.38),
        "ring": (-0.06, 0.36), "pinky": (-0.14, 0.33)}
_FINGER_LEN = {"index": 0.32, "middle": 0.345, "ring": 0.325, "pinky": 0.265}
# Phalanx lengths as fractions of the finger, and the angle each joint folds
# through at full curl. Three hinges is what makes a fist land BELOW the
# knuckle line instead of merely at it — the behaviour the ratio depends on.
_SPLIT = (0.45, 0.31, 0.24)
_BEND_DEG = (95.0, 105.0, 80.0)

_FINGER_ORDER = ("index", "middle", "ring", "pinky")
# Landmark index of each finger's MCP; PIP/DIP/TIP follow it.
_FINGER_BASE = {"index": 5, "middle": 9, "ring": 13, "pinky": 17}

# Thumb chain in hand space: CMC, MCP, IP. The tip is placed separately.
# The chain runs LATERALLY, not parallel to the index: a thumb that shares
# the index's direction has its tip sitting on the arc the index sweeps while
# curling, which fakes a pinch out of every half-closed hand.
_THUMB = ((0.09, 0.10), (0.21, 0.17), (0.31, 0.24))
_THUMB_TIP_OPEN = (0.40, 0.30)      # splayed clear of the fingers
_THUMB_TIP_WRAPPED = (0.02, 0.28)   # folded across the curled fingers

# Placement of the hand inside the normalized frame.
_ORIGIN = (0.5, 0.86)
_SCALE = 0.55


class _Landmark:
    __slots__ = ("x", "y", "z")

    def __init__(self, x, y, z=0.0):
        self.x, self.y, self.z = x, y, z


class _Category:
    def __init__(self, name):
        self.category_name = name


class _HandResult:
    """Minimal stand-in for MediaPipe's HandLandmarkerResult."""

    def __init__(self, hands, labels):
        self.hand_landmarks = hands
        self.handedness = [[_Category(n)] for n in labels]


def _to_image(p):
    """Hand space (+y up) -> normalized image coords (+y down)."""
    return (_ORIGIN[0] + p[0] * _SCALE, _ORIGIN[1] - p[1] * _SCALE)


def _finger_joints(name, curl):
    """MCP, PIP, DIP, TIP of one finger at `curl` in [0, 1] (0 = straight)."""
    mx, my = _MCP[name]
    length = _FINGER_LEN[name]
    norm = math.hypot(mx, my)
    dx, dy = mx / norm, my / norm      # extended direction: radially outward
    x, y, ang = mx, my, 0.0
    out = [(mx, my)]
    for frac, bend in zip(_SPLIT, _BEND_DEG):
        ang += math.radians(bend * curl)
        ux = dx * math.cos(ang) + dy * math.sin(ang)   # curl toward the palm
        uy = -dx * math.sin(ang) + dy * math.cos(ang)
        x += ux * length * frac
        y += uy * length * frac
        out.append((x, y))
    return out


def make_hand(curl=0.0, pinch=0.0, thumb_wrap=0.0):
    """21 landmarks. `curl` closes the four fingers, `pinch` walks the thumb
    tip onto the index tip, `thumb_wrap` folds it across a closed fist."""
    pts = {}
    for name in _FINGER_ORDER:
        base = _FINGER_BASE[name]
        for i, joint in enumerate(_finger_joints(name, curl)):
            pts[base + i] = joint
    pts[0] = (0.0, 0.0)
    for i, joint in enumerate(_THUMB):
        pts[1 + i] = joint

    ox, oy = _THUMB_TIP_OPEN
    wx, wy = _THUMB_TIP_WRAPPED
    tx = ox + (wx - ox) * thumb_wrap
    ty = oy + (wy - oy) * thumb_wrap
    ix, iy = pts[8]                                    # index tip
    pts[4] = (tx + (ix - tx) * pinch, ty + (iy - ty) * pinch)

    return [_Landmark(*_to_image(pts[i])) for i in range(21)]


# --- poses under test -----------------------------------------------------
# (name, landmarks, description)
POSES = {
    "open": (make_hand(curl=0.0, pinch=0.0),
             "flat hand, fingers out, thumb splayed"),
    "relaxed": (make_hand(curl=0.25, pinch=0.0),
                "the pose a hand rests in when held up at a screen"),
    "pinch": (make_hand(curl=0.0, pinch=1.0),
              "fingers out, thumb and index tips touching"),
    "fist": (make_hand(curl=0.9, pinch=0.0, thumb_wrap=0.0),
             "hand closed, thumb held clear alongside"),
}

# Which poses must CLOSE the cursor in each mode.
EXPECTED = {
    "pinch": {"pinch"},
    "fist": {"fist"},
    "either": {"pinch", "fist"},
}

# Reported but NOT asserted: a fist with the thumb folded across the fingers
# puts the thumb tip somewhere near the (hidden) index tip, so it lands close
# to the pinch threshold from either side depending on how the visitor tucks
# their thumb. That borderline is the whole reason this mode exists — the app
# has told visitors to "close your hand" since the first hint text, while the
# detector was only ever watching two fingertips, so a closed hand worked or
# not depending on thumb habit. Printed with its ratio so a real change in
# that margin is visible; not pinned to a pass/fail, because pinning a
# coin-flip is how a test starts lying.
INFO_POSES = {
    "fist_wrapped": make_hand(curl=0.9, pinch=0.0, thumb_wrap=1.0),
}

FAILURES = []


def _check(cond, msg):
    if not cond:
        FAILURES.append(msg)
    return cond


def _load(mode):
    """Re-import config + gestures under HALL_GESTURE=<mode>.

    Both read the mode at import time (the anchor choice and the fist->pinch
    unit gain are module constants), so a reload is what actually switches
    modes inside one process.
    """
    os.environ["HALL_GESTURE"] = mode
    import config
    importlib.reload(config)
    from detection import gestures
    importlib.reload(gestures)
    return gestures


def _run(gestures, landmarks, frames=12, t0=100.0):
    """Feed one static pose for N frames; return (fired, machine)."""
    result = _HandResult([landmarks], ["Right"])
    fired = False
    for i in range(frames):
        gestures.update_pinches(result, W, H, now=t0 + i / 30.0)
        _, machine = gestures.pinch_infos()[0]
        fired = fired or machine.pinching
    return fired, machine


def _run_transition(gestures, first, second, frames=12, t0=200.0):
    """Hold `first`, then `second`; return whether the close fired during the
    SECOND pose. This is how a real gesture arrives — the machine refuses to
    fire for a hand that was already closed when it appeared, so a pose can
    only be tested for firing by transitioning into it."""
    _run(gestures, first, frames=frames, t0=t0)
    result = _HandResult([second], ["Right"])
    fired = False
    for i in range(frames):
        gestures.update_pinches(result, W, H,
                                now=t0 + (frames + i) / 30.0)
        _, machine = gestures.pinch_infos()[0]
        fired = fired or machine.pinching
    return fired, machine


def check_mode(mode):
    gestures = _load(mode)
    print(f"\n--- HALL_GESTURE={mode} " + "-" * (52 - len(mode)))

    for name, (landmarks, _desc) in POSES.items():
        gestures._pinch_machines.clear()
        fired, machine = _run_transition(gestures, POSES["open"][0], landmarks)
        should = name in EXPECTED[mode]
        verdict = "closed" if fired else "open  "
        mark = "ok " if fired == should else "FAIL"
        print(f"  {mark} {name:<13} {verdict}  "
              f"ratio {machine.ratio:.3f}  held={machine.closed}")
        _check(fired == should,
               f"{mode}: pose {name!r} {'did not close' if should else 'closed'} "
               f"the cursor (ratio {machine.ratio:.3f})")

    for name, landmarks in INFO_POSES.items():
        gestures._pinch_machines.clear()
        fired, machine = _run_transition(gestures, POSES["open"][0], landmarks)
        print(f"  --  {name:<13} {'closed' if fired else 'open  '}  "
              f"ratio {machine.ratio:.3f}  (informational)")

    # A hand that ENTERS the frame already closed must never fire: otherwise a
    # visitor walking past with a closed hand presses whatever it passes over.
    gestures._pinch_machines.clear()
    closing_pose = "pinch" if mode == "pinch" else "fist"
    fired, machine = _run(gestures, POSES[closing_pose][0])
    _check(not fired,
           f"{mode}: a hand appearing already closed fired a click")
    _check(machine.closed,
           f"{mode}: a hand appearing already closed did not start held")
    print(f"  {'ok ' if not fired else 'FAIL'} enters-closed  silent "
          f"held={machine.closed}")

    # ...and releasing it works, so the visitor is not stuck holding.
    result = _HandResult([POSES["open"][0]], ["Right"])
    for i in range(12):
        gestures.update_pinches(result, W, H, now=400.0 + i / 30.0)
    _, machine = gestures.pinch_infos()[0]
    _check(not machine.closed, f"{mode}: opening the hand did not release")
    print(f"  {'ok ' if not machine.closed else 'FAIL'} release        "
          f"held={machine.closed}")

    # The cursor must land ON the hand it is tracking. Measured against the
    # palm knuckle in units of the hand's own size, so the check means the
    # same thing at any camera distance and for either anchor. An anchor that
    # picked a landmark the gesture moves shows up here as a cursor floating
    # off the hand.
    pose = POSES[closing_pose][0]
    gestures._pinch_machines.clear()
    _run(gestures, pose, frames=20)
    _, machine = gestures.pinch_infos()[0]
    cx, cy = machine.cursor
    palm = pose[9]
    scale = gestures.hand_scale(pose, W, H)
    offset = math.hypot(cx - palm.x * W, cy - palm.y * H) / scale
    near = offset <= 1.5
    _check(near, f"{mode}: cursor sits {offset:.2f} hand-widths from the palm")
    print(f"  {'ok ' if near else 'FAIL'} cursor         "
          f"{offset:.2f} hand-widths from the palm")


def check_degenerate():
    """A collapsed hand must not crash or invent a closure.

    Every landmark on one point is what a badly-cropped or half-visible hand
    degenerates toward, and it makes both |MCP - wrist| and the hand scale
    zero. main.py's per-frame try/except would swallow the exception and stop
    publishing state, freezing the kiosk.
    """
    gestures = _load("either")
    gestures._pinch_machines.clear()
    flat = [_Landmark(0.5, 0.5, 0.0) for _ in range(21)]
    fired, machine = _run(gestures, flat)
    _check(not fired, "degenerate hand fired a click")
    print(f"\n  {'ok ' if not fired else 'FAIL'} degenerate hand survived "
          f"(ratio={machine.ratio})")


def ratio_table():
    """Print the fist ratio across the curl range — the reference for the
    on-camera tuning pass (compare against HALL_DEBUG=1's live readout)."""
    gestures = _load("either")
    from config import FIST_CLOSE_RATIO, FIST_RELEASE_RATIO
    print("\n--- fist ratio vs finger curl " + "-" * 39)
    print(f"  thresholds: close < {FIST_CLOSE_RATIO}  "
          f"release > {FIST_RELEASE_RATIO}")
    for curl in (0.0, 0.2, 0.35, 0.5, 0.65, 0.8, 0.9, 1.0):
        landmarks = make_hand(curl=curl)
        ratio = gestures.fist_ratio(landmarks, W, H)
        state = ("CLOSE" if ratio < FIST_CLOSE_RATIO
                 else "open" if ratio > FIST_RELEASE_RATIO else "  ~  ")
        print(f"  curl {curl:.2f}   ratio {ratio:.3f}   {state}")


def main():
    for mode in ("pinch", "fist", "either"):
        check_mode(mode)
    check_degenerate()
    ratio_table()

    print()
    if FAILURES:
        for f in FAILURES:
            print(f"FAIL: {f}")
        print(f"\n{len(FAILURES)} failure(s)")
        return 1
    print("all gesture modes OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
