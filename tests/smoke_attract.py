"""Exercise attract mode: presence detection and the phase machine.

    uv run python tests/smoke_attract.py

Why this exists, in the same spirit as smoke_scenes.py: attract mode decides
whether the exhibit shows anything at all. A phase machine that never leaves
"attract" leaves a slideshow running while somebody stands in front of it
waving, and one that never returns to it leaves the last visitor's half-built
black hole up all night. Neither raises an exception, so `main.py`'s
per-frame try/except cannot catch either — the kiosk just looks broken to
whoever walks up.

So: drive a real UIManager through the whole cycle with synthetic frames,
asserting each transition, and run BOTH renderers (`draw()` and
`to_state()`) in every phase, since those are what main.py calls.

WHAT THIS DOES NOT DO: validate the presence thresholds. A bright rectangle
pasted into a black frame is not a person in a corridor, so it proves the
machine reacts to motion, not that PRESENCE_ENTER_FRAC is right for the
hall. Tune that on the device with HALL_DEBUG=1, which prints the live
motion fraction next to its thresholds.
"""

import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))
sys.path.insert(0, _HERE)

import numpy as np  # noqa: E402
from smoke_gestures import make_hand  # noqa: E402

from config import (ATTRACT_IDLE_S, GREETING_S, PRESENCE_ENTER_S,  # noqa: E402
                    PRESENCE_WARMUP_S)
from ui.manager import UIManager  # noqa: E402
from ui.presence import PresenceDetector  # noqa: E402

W, H = 640, 360
FAILURES = []

# A controllable clock, installed over time.monotonic for the whole run.
# Everything under test reads the clock as `time.monotonic()` (an attribute
# lookup, not a from-import), so one patch covers the manager, the presence
# detector, the slideshow and the gesture machines at once — and every
# object built while it is installed anchors its timestamps to the same
# timeline. Starting from the real clock keeps monotonic() monotonic for
# anything that sampled it before the patch.
CLOCK = [time.monotonic()]
_REAL_MONOTONIC = time.monotonic


def install_clock():
    time.monotonic = lambda: CLOCK[0]


def restore_clock():
    time.monotonic = _REAL_MONOTONIC


def advance(seconds, fps=30.0, step=None):
    """Yield each tick of `seconds` of fake time."""
    dt = 1.0 / fps
    for _ in range(max(int(seconds * fps), 1)):
        CLOCK[0] += dt
        if step is not None:
            step()


def _check(cond, msg):
    if not cond:
        FAILURES.append(msg)
    print(f"  {'ok  ' if cond else 'FAIL'} {msg}")
    return cond


def empty_room():
    """A dim, static frame with a little texture — the background."""
    frame = np.zeros((H, W, 3), np.uint8)
    frame[:] = 28
    frame[H // 2:, :] = 44
    return frame


def visitor(frame):
    """The same room with somebody filling a good part of it."""
    out = frame.copy()
    out[H // 4:, W // 4:3 * W // 4] = 210
    return out


class _HandResult:
    """MediaPipe HandLandmarkerResult stand-in around one posed hand."""

    def __init__(self, landmarks=None):
        self.hand_landmarks = [landmarks or make_hand(curl=0.0)]
        self.handedness = []


def _run(ui, frame, hand=None, seconds=1.0, fps=30.0):
    """Feed one situation for `seconds` of fake time."""
    advance(seconds, fps, step=lambda: ui.update(hand, None, frame=frame))
    return ui.phase


def check_presence():
    """The detector on its own: empty room quiet, visitor detected, and a
    visitor who stops moving stays detected (the background must not learn
    them)."""
    print("\n--- presence detector " + "-" * 47)
    det = PresenceDetector()
    room = empty_room()
    t = CLOCK[0]
    for _ in range(int((PRESENCE_WARMUP_S + 2.0) * 30)):  # learn the room
        t += 1 / 30
        det.update(room, now=t)
    _check(not det.present, "empty room reads as absent")
    _check(det.motion_frac < 0.01,
           f"empty room motion is negligible ({det.motion_frac:.4f})")

    person = visitor(room)
    for _ in range(int((PRESENCE_ENTER_S + 0.5) * 30)):
        t += 1 / 30
        det.update(person, now=t)
    _check(det.present, "somebody filling the frame reads as present")
    _check(det.source == "motion", f"...via motion (got {det.source})")

    # The point of freezing the background while present: a visitor who
    # stops moving is still a visitor.
    for _ in range(int(30 * 30)):             # 30 s perfectly still
        t += 1 / 30
        det.update(person, now=t)
    _check(det.present,
           "a visitor standing perfectly still for 30 s stays detected")

    for _ in range(int(3 * 30)):
        t += 1 / 30
        det.update(room, now=t)
    _check(not det.present, "the room emptying reads as absent again")

    # A hand alone is enough, with no motion signal at all.
    det2 = PresenceDetector()
    det2.update(None, hand_result=_HandResult(), now=CLOCK[0])
    _check(det2.present and det2.source == "hand",
           "a tracked hand asserts presence with no frame at all")


def check_phases():
    """The manager's attract -> greeting -> live -> attract cycle."""
    print("\n--- phase machine " + "-" * 51)
    ui = UIManager(W, H, gpu_effects=False)
    room = empty_room()
    person = visitor(room)

    _check(ui.phase == "attract", "boots into attract")
    _run(ui, room, seconds=PRESENCE_WARMUP_S + 2.0)
    _check(ui.phase == "attract", "stays in attract with an empty room")

    _run(ui, person, seconds=PRESENCE_ENTER_S + 0.7)
    _check(ui.phase == "greeting", "somebody walking up triggers the greeting")

    _run(ui, person, seconds=GREETING_S + 0.5)
    _check(ui.phase == "live", "the greeting hands over to the live UI")

    # Enter an experiment, then leave: the next visitor must not inherit it.
    ui._set_state("experiments")
    ui._spawn_slingshot()
    _run(ui, room, seconds=1.0)
    _check(ui.phase == "live",
           "a brief absence does NOT drop out of live (idle timer)")

    ui._last_present_t -= ATTRACT_IDLE_S + 1.0
    _run(ui, room, seconds=0.2)
    _check(ui.phase == "attract", "sustained absence returns to attract")
    _check(ui._active_experiment is None and ui.state == "menu",
           "leaving resets the app, so the next visitor starts clean")

    # ...and the onboarding hint comes back for that next visitor.
    ui._has_interacted = True
    _run(ui, person, seconds=PRESENCE_ENTER_S + 0.7)
    _check(ui.phase == "greeting" and not ui._has_interacted,
           "the next visitor gets the onboarding hint back")

    # Making the gesture skips the rest of the greeting. Driven with real
    # posed landmarks rather than a faked machine: the manager reads the
    # gesture through update_pinches, which discards stale machines, so a
    # stub is both fragile and no evidence the integration works.
    from detection import gestures
    gestures._pinch_machines.clear()
    _run(ui, person, hand=_HandResult(make_hand(curl=0.0)), seconds=0.4)
    still_greeting = ui.phase == "greeting"
    _check(still_greeting, "an OPEN hand does not skip the greeting")
    _run(ui, person, hand=_HandResult(make_hand(curl=0.9)), seconds=0.4)
    _check(ui.phase == "live",
           "closing your hand skips the rest of the greeting")
    gestures._pinch_machines.clear()


def check_renderers():
    """Both renderers, in every phase — the pair main.py actually calls."""
    print("\n--- renderers " + "-" * 55)
    ui = UIManager(W, H, gpu_effects=False)
    room = empty_room()
    person = visitor(room)

    # Let the presence warm-up pass with an empty room first, the way the
    # exhibit actually boots.
    _run(ui, room, seconds=PRESENCE_WARMUP_S + 0.5)

    for phase, frame in (("attract", room), ("greeting", person),
                         ("live", person)):
        if phase == "greeting":
            _run(ui, person, seconds=PRESENCE_ENTER_S + 0.7)
        elif phase == "live":
            _run(ui, person, seconds=GREETING_S + 0.5)
        _check(ui.phase == phase, f"reached phase {phase!r}")

        out = np.zeros((H, W, 3), np.uint8)
        try:
            ui.draw(out)
            drew = True
        except Exception as exc:               # noqa: BLE001
            drew = False
            print(f"       draw() raised: {exc!r}")
        _check(drew, f"{phase}: cv2 draw() runs")
        _check(out.any(), f"{phase}: cv2 draw() puts something on the frame")

        state = ui.to_state()
        payload = json.dumps(state)            # the SSE endpoint does this
        _check(state["session"]["phase"] == phase,
               f"{phase}: to_state() reports the phase")
        _check(len(payload) < 20000,
               f"{phase}: state payload stays small ({len(payload)} B)")

    slides = ui._attract.to_state()["slides"]
    _check(bool(slides),
           f"the slideshow found images in ATTRACT_DIR ({len(slides)} slides)")
    _check(all(s["src"].startswith("/attract/") for s in slides),
           "every slide is served from the /attract/ route")


def main():
    install_clock()
    try:
        check_presence()
        check_phases()
        check_renderers()
    finally:
        restore_clock()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} failure(s)")
        return 1
    print("attract mode OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
