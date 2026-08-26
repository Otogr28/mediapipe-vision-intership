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

The operator override (`control.py`, `deploy/hall-app/hallidle`) is checked
here too, at both ends: the phase machine honouring it against a visitor who
is standing right there, and the HTTP route it arrives on, served by a real
WebSink on a throwaway port.

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
                    PRESENCE_STATIC_RELEASE_S, PRESENCE_WARMUP_S)
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
    """The same room with somebody CLOSE: one tall blob, most of the height."""
    out = frame.copy()
    out[H // 4:, W // 4:3 * W // 4] = 210
    return out


def distant_visitor(frame):
    """Somebody down the corridor: a small patch, high in the frame.

    The exhibit must ignore this. It is the case that made attract mode
    useless before the size gates — every passer-by woke the display, so the
    slideshow was never on screen and the app reset itself under whoever was
    actually standing at it.
    """
    out = frame.copy()
    top = H // 8
    out[top:top + H // 5, W // 2:W // 2 + W // 10] = 210
    return out


def flicker(frame):
    """Scattered change covering a LOT of the frame but forming no tall blob
    — a screen behind, a strip light, sun through leaves. Its total changed
    fraction beats the old threshold; its largest blob does not."""
    out = frame.copy()
    for row in range(6):
        for col in range(10):
            y = int(H * (0.05 + 0.15 * row))
            x = int(W * (0.02 + 0.098 * col))
            out[y:y + H // 20, x:x + W // 20] = 210
    return out


class _LM:
    """Landmark stand-in — the detectors only ever expose .x/.y/.z."""

    def __init__(self, x, y, z=0.0):
        self.x, self.y, self.z = x, y, z


def scaled_hand(landmarks, scale, cx=0.5, cy=0.5):
    """The same posed hand, smaller in frame — i.e. further from the camera."""
    return [_LM(cx + (lm.x - cx) * scale, cy + (lm.y - cy) * scale,
                getattr(lm, "z", 0.0)) for lm in landmarks]


class _HandResult:
    """MediaPipe HandLandmarkerResult stand-in around one posed hand."""

    def __init__(self, landmarks=None):
        self.hand_landmarks = [landmarks or make_hand(curl=0.0)]
        self.handedness = []


def _run(ui, frame, hand=None, seconds=1.0, fps=30.0):
    """Feed one situation for `seconds` of fake time."""
    advance(seconds, fps, step=lambda: ui.update(hand, None, frame=frame))
    return ui.phase


def check_hand_mode():
    """The DEFAULT presence mode (config.PRESENCE_MODE == "hand"): only a
    hand big enough in frame counts. The operator's rule — show it a hand,
    it goes live; hide your hands for ATTRACT_IDLE_S, the slideshow returns.
    Motion must be completely inert, or somebody watching the slideshow
    keeps it off just by standing there."""
    print("\n--- hand-only mode (the default) " + "-" * 36)
    room = empty_room()

    det = PresenceDetector()
    _check(det.mode == "hand", f"the default mode is hand ({det.mode})")
    t = CLOCK[0]
    for _ in range(int((PRESENCE_WARMUP_S + 2.0) * 30)):
        t += 1 / 30
        det.update(room, now=t)
    _check(not det.present, "empty room reads as absent")

    # A person-sized moving blob — the thing that wakes "full" mode — must
    # do NOTHING here.
    for _ in range(int((PRESENCE_ENTER_S + 2.0) * 30)):
        t += 1 / 30
        det.update(visitor(room), now=t)
    _check(not det.present,
           "somebody standing in frame WITHOUT showing a hand stays absent")

    t += 1 / 30
    det.update(visitor(room), hand_result=_HandResult(), now=t)
    _check(det.present and det.source == "hand",
           "a hand at the screen asserts presence on the spot")

    t += 1 / 30
    det.update(visitor(room), hand_result=None, now=t)
    _check(not det.present,
           "hiding the hand releases it on the next frame "
           "(UIManager's idle timer owns the 5 s)")

    small = _HandResult(scaled_hand(make_hand(curl=0.0), 0.2))
    t += 1 / 30
    det.update(visitor(room), hand_result=small, now=t)
    _check(not det.present,
           f"a hand across the room is still too small (span "
           f"{det.hand_span:.2f} < gate)")


def check_presence():
    """The FULL mode (HALL_PRESENCE=full) detector on its own: empty room
    quiet, visitor detected, and a visitor who stops moving stays detected
    (the background must not learn them)."""
    print("\n--- presence detector (full mode) " + "-" * 35)
    det = PresenceDetector(mode="full")
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

    # A hand alone is enough, with no motion signal at all — as long as it is
    # big enough in frame to be a hand at the screen.
    det2 = PresenceDetector(mode="full")
    det2.update(None, hand_result=_HandResult(), now=CLOCK[0])
    _check(det2.present and det2.source == "hand",
           "a hand held at the screen asserts presence with no frame at all")


def check_distance():
    """The size gates: only somebody CLOSE wakes the exhibit.

    Synthetic frames cannot tell you whether PRESENCE_ENTER_SPAN is right for
    the hall (tune that on the device with HALL_DEBUG=1). What they can prove
    is the shape of the rule — that a small disturbance and a scattered one
    are both rejected while a tall one is accepted — which is what separates
    a visitor at the screen from the corridor behind them.
    """
    print("\n--- distance gates " + "-" * 50)
    room = empty_room()

    def settled():
        det = PresenceDetector(mode="full")
        t = CLOCK[0]
        for _ in range(int((PRESENCE_WARMUP_S + 2.0) * 30)):
            t += 1 / 30
            det.update(room, now=t)
        return det, t

    def feed(det, t, frame, seconds=PRESENCE_ENTER_S + 1.0):
        for _ in range(int(seconds * 30)):
            t += 1 / 30
            det.update(frame, now=t)
        return t

    det, t = settled()
    feed(det, t, distant_visitor(room))
    _check(not det.present,
           f"somebody far down the corridor is ignored "
           f"(blob {det.blob_frac:.3f}, tall {det.blob_span:.2f})")

    det, t = settled()
    feed(det, t, flicker(room))
    _check(det.motion_frac >= 0.14,
           f"...the flicker frame DOES move a lot of pixels "
           f"({det.motion_frac:.3f}) — the old test would have woken on it")
    _check(not det.present,
           f"scattered flicker with no tall blob is ignored "
           f"(blob {det.blob_frac:.3f}, tall {det.blob_span:.2f})")

    det, t = settled()
    feed(det, t, visitor(room))
    _check(det.present,
           f"somebody at the screen still wakes it "
           f"(blob {det.blob_frac:.3f}, tall {det.blob_span:.2f})")

    # ...and the same gate on the hand signal.
    small = _HandResult(scaled_hand(make_hand(curl=0.0), 0.2))
    det = PresenceDetector(mode="full")
    det.update(None, hand_result=small, now=CLOCK[0])
    _check(not det.present,
           f"a hand across the room is not a visitor "
           f"(span {det.hand_span:.2f})")


def check_static_release():
    """The presence latch-up, and the escape hatch that breaks it.

    The background EMA freezes while somebody is present, and presence only
    releases when the frame matches that background again — so a global
    brightness shift during a visit (the camera's auto-exposure re-adapting
    around the visitor) used to leave the EMPTY room reading as one
    frame-wide blob forever: present never released, the background never
    re-learned, and the idle slideshow never came back after somebody used
    an experiment. The escape hatch rules a difference with zero
    frame-to-frame life in it for PRESENCE_STATIC_RELEASE_S to be scenery.
    """
    print("\n--- static release (presence latch-up) " + "-" * 30)
    room = empty_room()
    # The same empty room after the exposure shift: globally brighter by
    # more than PRESENCE_PIXEL_DELTA, so every pixel differs from the
    # learned background at once.
    shifted = np.clip(room.astype(np.int16) + 40, 0, 255).astype(np.uint8)

    det = PresenceDetector(mode="full")
    t = CLOCK[0]
    for _ in range(int((PRESENCE_WARMUP_S + 2.0) * 30)):
        t += 1 / 30
        det.update(room, now=t)
    for _ in range(int((PRESENCE_ENTER_S + 0.5) * 30)):
        t += 1 / 30
        det.update(visitor(room), now=t)
    _check(det.present, "visitor asserted via motion (the latch precondition)")

    # Visitor leaves; the exposure shift they caused stays. Without the
    # escape hatch this held `present` forever.
    for _ in range(int(5.0 * 30)):
        t += 1 / 30
        det.update(shifted, now=t)
    _check(det.present,
           "the stale-background blob does keep presence at first (latched)")
    for _ in range(int((PRESENCE_STATIC_RELEASE_S + 2.0) * 30)):
        t += 1 / 30
        det.update(shifted, now=t)
    _check(not det.present,
           f"a dead frame-wide difference releases within "
           f"{PRESENCE_STATIC_RELEASE_S:.0f} s (still {det.still_s:.0f} s)")
    for _ in range(int(5.0 * 30)):
        t += 1 / 30
        det.update(shifted, now=t)
    _check(not det.present and det.blob_frac < 0.01,
           "...and the re-seeded background keeps the empty room absent")

    # End to end, in the DEFAULT hand-only mode: the latch cannot form at
    # all, because the picture is never consulted. A visit that bakes in an
    # exposure shift still hands the slideshow back on the idle timer.
    ui = UIManager(W, H, gpu_effects=False)
    hand = _HandResult()
    _run(ui, room, seconds=PRESENCE_WARMUP_S + 2.0)
    _run(ui, room, hand=hand, seconds=0.3)
    _run(ui, room, hand=hand, seconds=GREETING_S + 0.5)
    _check(ui.phase == "live", "a raised hand walked up to a live exhibit")
    ui._set_state("experiments")
    ui._spawn_slingshot()
    _run(ui, shifted, seconds=ATTRACT_IDLE_S + 2.0)
    _check(ui.phase == "attract",
           "an exposure shift baked in during the visit no longer keeps the "
           "slideshow away — hand mode never consults the picture")


def check_phases():
    """The manager's attract -> greeting -> live -> attract cycle, driven
    the way the default hand-only mode is driven: by a hand appearing and
    disappearing. (A person-shaped motion blob no longer wakes it — that is
    check_hand_mode's business.)"""
    print("\n--- phase machine " + "-" * 51)
    ui = UIManager(W, H, gpu_effects=False)
    room = empty_room()
    person = visitor(room)
    hand = _HandResult()

    _check(ui.phase == "attract", "boots into attract")
    _run(ui, room, seconds=PRESENCE_WARMUP_S + 2.0)
    _check(ui.phase == "attract", "stays in attract with an empty room")

    _run(ui, person, seconds=PRESENCE_ENTER_S + 2.0)
    _check(ui.phase == "attract",
           "somebody in frame WITHOUT a hand up does not wake it")

    _run(ui, person, hand=hand, seconds=0.3)
    _check(ui.phase == "greeting", "a raised hand triggers the greeting")

    _run(ui, person, hand=hand, seconds=GREETING_S + 0.5)
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
    _run(ui, person, hand=hand, seconds=0.3)
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
    # exhibit actually boots. Arrival is a raised hand (the default
    # hand-only presence mode).
    hand = _HandResult()
    _run(ui, room, seconds=PRESENCE_WARMUP_S + 0.5)

    for phase, frame in (("attract", room), ("greeting", person),
                         ("live", person)):
        if phase == "greeting":
            _run(ui, person, hand=hand, seconds=0.3)
        elif phase == "live":
            _run(ui, person, hand=hand, seconds=GREETING_S + 0.5)
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

    att = ui._attract.to_state()
    _check(att["count"] > 0,
           f"the slideshow found images ({att['count']} slides)")
    _check(att["current"] is not None
           and att["current"]["src"].startswith("/attract/"),
           "the current slide is served from the /attract/ route")
    _check("slides" not in att,
           "the payload carries a window, not the whole folder")


def check_gallery():
    """The gallery folder: what makes adding a photograph a file copy.

    Written against a temporary directory rather than the device's real one,
    since the point is the RULE (a folder with images wins, an empty or
    missing one falls back to the repo stills) and not what happens to be on
    this machine.
    """
    print("\n--- gallery folder " + "-" * 50)
    import shutil
    import tempfile

    import config
    from ui import attract as attract_mod

    tmp = tempfile.mkdtemp(prefix="hall-gallery-")
    original = config.ATTRACT_GALLERY_DIR
    try:
        # Empty folder -> the repo's experiment stills, captions and all.
        config.ATTRACT_GALLERY_DIR = tmp
        attract_mod.ATTRACT_GALLERY_DIR = tmp
        _check(attract_mod.slides_dir() == config.ATTRACT_DIR,
               "an empty gallery falls back to the repo stills")
        _check(any(s["title"] for s in attract_mod.build_slides()),
               "...which still carry their experiment captions")

        # A file straight off a phone: spaces, parentheses, upper-case
        # extension, plus the zero-byte file a half-finished copy leaves.
        source = os.path.join(config.ATTRACT_DIR, "waves.jpg")
        for name in ("hall (1).JPG", "20250919_171142.jpg"):
            shutil.copyfile(source, os.path.join(tmp, name))
        open(os.path.join(tmp, "truncated.jpg"), "wb").close()

        _check(attract_mod.slides_dir() == tmp,
               "a gallery with photographs in it wins")
        slides = attract_mod.build_slides()
        _check(len(slides) == 2,
               f"the zero-byte file is skipped ({len(slides)} slides, want 2)")
        _check(all(s["title"] == "" and s["caption"] == "" for s in slides),
               "gallery photographs get no camera-filename caption")
        spaced = [s for s in slides if "hall" in s["src"]]
        _check(bool(spaced) and " " not in spaced[0]["src"]
               and "%20" in spaced[0]["src"],
               f"spaces are percent-encoded for the route "
               f"({spaced[0]['src'] if spaced else '--'})")

        # And the rescan: a photograph copied in joins without a restart.
        screen = attract_mod.AttractScreen(W, H)
        _check(len(screen.slides) == 2, "the screen picked up the gallery")
        shutil.copyfile(source, os.path.join(tmp, "zzz_new.jpg"))
        screen.enter(CLOCK[0])
        _check(len(screen.slides) == 3,
               "a photograph copied in joins the rotation on the next rescan")
    finally:
        config.ATTRACT_GALLERY_DIR = original
        attract_mod.ATTRACT_GALLERY_DIR = original
        shutil.rmtree(tmp, ignore_errors=True)


def check_forced_idle():
    """The operator override: `hallidle on` pinning the exhibit to the
    slideshow while somebody is standing in front of it.

    Two things are worth asserting and neither raises on its own. A force
    that presence can overrule is useless — the whole point is showing the
    photographs to the people who are there, so the visitor in frame must not
    take them away again. And a release has to hand back a *live* exhibit
    immediately, because the operator flipped it off in front of an audience.
    """
    print("\n--- forced idle (hallidle) " + "-" * 42)
    import control

    ui = UIManager(W, H, gpu_effects=False)
    room = empty_room()
    person = visitor(room)
    hand = _HandResult()

    _run(ui, room, seconds=PRESENCE_WARMUP_S + 2.0)
    _run(ui, person, hand=hand, seconds=0.3)
    _run(ui, person, hand=hand, seconds=GREETING_S + 0.5)
    _check(ui.phase == "live", "starts live, with a visitor's hand in frame")
    ui._set_state("experiments")
    ui._spawn_slingshot()

    control.set_forced_idle(True)
    _run(ui, person, hand=hand, seconds=0.2)
    _check(ui.phase == "attract", "forcing idle takes over mid-visit")
    _check(ui._active_experiment is None and ui.state == "menu",
           "...and resets the app, leaving nothing half-built behind it")

    _run(ui, person, hand=hand, seconds=ATTRACT_IDLE_S + 2.0)
    _check(ui.phase == "attract",
           "a visitor's hand at the screen does NOT release the force")

    out = np.zeros((H, W, 3), np.uint8)
    ui.draw(out)
    _check(out.any(), "the slideshow is what gets drawn while forced")

    control.set_forced_idle(False)
    _run(ui, person, hand=hand, seconds=0.2)
    _check(ui.phase == "greeting",
           "releasing it greets whoever is standing there, same frame")
    control.reset()


def check_control_endpoint():
    """The wire `hallidle` talks over: POST /control/idle on a real WebSink.

    Worth a check because the failure is silent. `WebSink` dispatches GET by
    path and falls through to the static frontend, so a route left out of its
    pass-through list answers `index.html` (or 404) with a 200-looking shape,
    and its POST handler is inherited rather than written — exactly the wiring
    a reader assumes works.
    """
    print("\n--- /control/idle " + "-" * 51)
    import threading
    import urllib.error
    import urllib.request

    import control
    from output import WebSink

    # Port 0: the kernel picks a free one, so this cannot collide with a
    # backend already running on 8092. Bound to loopback, not `auto` — that
    # would go asking Tailscale for an address.
    sink = WebSink(bind="127.0.0.1", port=0, dist_dir=None)
    port = sink._server.server_address[1]
    url = f"http://127.0.0.1:{port}/control/idle"

    def call(data=None):
        req = urllib.request.Request(
            url, data=None if data is None else data.encode(),
            method="GET" if data is None else "POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())

    stop = threading.Event()
    try:
        # Stand in for the render loop: keep publishing a payload, the way
        # main.py does once per frame. A POST waits for two fresh ones
        # (WebSink.settle_control) before answering, so without a publisher
        # every call here would sit out its timeout — and the phase in the
        # answer comes from this payload, which is what makes the wire test a
        # wire test and not a second copy of check_forced_idle.
        ui = UIManager(W, H, gpu_effects=False)
        _run(ui, empty_room(), seconds=0.2)
        payload = json.dumps(ui.to_state()).encode()

        def publisher():
            while not stop.wait(0.01):
                sink.publish_state(payload)

        threading.Thread(target=publisher, daemon=True).start()

        _check(call()["forced_idle"] is False, "GET reports the flag (off)")
        got = call("on")
        _check(got["forced_idle"] is True and control.forced_idle(),
               "POST 'on' forces idle")
        _check(got["phase"] == "attract",
               f"...and the status carries the app's phase ({got['phase']})")
        _check(isinstance(got.get("slide"), str)
               and got["slide"].startswith("/attract/"),
               f"...and which photograph is up ({got.get('slide')})")

        # A GET must never be able to blank the exhibit: the kiosk browser,
        # a crawler or a link preview all issue those.
        _check(call()["forced_idle"] is True, "GET does not change the flag")

        _check(call("off")["forced_idle"] is False, "POST 'off' releases it")

        code = None
        try:
            call("banana")
        except urllib.error.HTTPError as exc:
            code = exc.code
        _check(code == 400, f"a value that is neither on nor off is a 400 "
                            f"(got {code})")
        _check(control.forced_idle() is False,
               "...and leaves the exhibit alone")
    finally:
        stop.set()
        control.reset()
        sink.close()


def main():
    install_clock()
    try:
        check_hand_mode()
        check_presence()
        check_distance()
        check_static_release()
        check_phases()
        check_renderers()
        check_gallery()
        check_forced_idle()
        check_control_endpoint()
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
