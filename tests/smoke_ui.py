"""UIManager-level interaction rules: what wins when two things overlap.

    uv run python tests/smoke_ui.py

Why this exists: buttons float on top of the scene, and until now the two read
the same pinch snapshot independently with no idea about each other. Closing
your hand on the "+Q" button pressed the button *and* dropped a charge
underneath it; simply hovering a button while closing planted objects behind
it. Both halves reported from the exhibit.

Nothing raises, so `main.py`'s per-frame try/except cannot catch it and no
scene test notices — each half does exactly what it was asked. The rule only
exists between them, which is why it is tested here rather than in
`smoke_scenes.py`.

The rules under test:

1. A closing gesture over a live button presses the button and does NOT reach
   the scene.
2. A closing gesture over empty scene still reaches the scene (the fix must
   not simply mute everything).
3. A drag already under way survives being carried across a button — only the
   closing EVENT is withheld, never the hold.

Plain `python`, no pytest, runnable on the Jetson's system 3.10 like the rest.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))
sys.path.insert(0, _HERE)

import numpy as np  # noqa: E402
from smoke_gestures import make_hand  # noqa: E402

from detection import gestures  # noqa: E402
from ui.manager import UIManager  # noqa: E402

W, H = 1280, 720
FAILURES = []

# (spawn method, name, probe) — `probe` returns a number that GROWS when the
# scene accepts a closing gesture. Not all scenes place an object on the
# pinch edge: Orbitals starts AIMING and the body only appears on release,
# so its probe watches the gesture it started rather than a body count.
SCENES = [
    ("_spawn_charges", "Charges", lambda e: len(e.charges)),
    ("_spawn_magnets", "Magnets", lambda e: len(e.magnets)),
    ("_spawn_waves", "Waves", lambda e: len(e.sources)),
    ("_spawn_orbitals", "Orbitals", lambda e: int(e.aiming)),
]


def _check(cond, msg):
    if not cond:
        FAILURES.append(msg)
    print(f"  {'ok  ' if cond else 'FAIL'} {msg}")
    return cond


class _HandResult:
    def __init__(self, landmarks):
        self.hand_landmarks = [landmarks]
        self.handedness = []


def _hand_at(cx, cy, curl):
    """A posed hand whose CURSOR lands near (cx, cy) in frame pixels.

    `make_hand` builds the hand around a fixed origin, so the landmarks are
    shifted bodily; the cursor anchor rides with them.
    """
    landmarks = make_hand(curl=curl)
    # Where the anchor currently sits, in normalized coords.
    anchor = landmarks[9] if not gestures.USE_THUMB_ANCHOR else landmarks[4]
    dx = cx / W - anchor.x
    dy = cy / H - anchor.y
    for lm in landmarks:
        lm.x += dx
        lm.y += dy
    return landmarks


def _feed(ui, landmarks, frames=10):
    """Run the manager for N frames with one posed hand held still."""
    result = _HandResult(landmarks)
    blank = np.zeros((H, W, 3), np.uint8)
    for _ in range(frames):
        ui.update(result, None, frame=blank)
    return result


def _live_manager():
    """A UIManager pinned live (attract mode is a separate concern)."""
    ui = UIManager(W, H, gpu_effects=False)
    ui.phase = "live"
    gestures._pinch_machines.clear()
    return ui


def _centre(btn):
    return (btn.x + btn.width / 2, btn.y + btn.height / 2)


def _button_centre(ui, want_id):
    for bid, btn in ui._active_buttons():
        if bid == want_id:
            return bid, btn, _centre(btn)
    return None, None, None


def _scene_palette_button(ui):
    """The scene's own first palette button — a type selector in every scene
    that has one.

    This is the button the complaint is really about, and the ONLY kind that
    tests the reservation: it leaves the experiment running, so the scene is
    still there to wrongly take the gesture. Reset changes `state`, which
    skips the scene dispatch entirely and would let a broken build pass.
    """
    for bid, btn in ui._experiment_palette():
        return bid, btn, _centre(btn)
    return None, None, None


def check_button_beats_scene():
    """Rule 1 + 2, on every scene that acts on a closing gesture."""
    print("\n--- a button in front swallows the gesture " + "-" * 26)

    for spawn, name, count in SCENES:
        ui = _live_manager()
        ui._set_state("experiments")
        getattr(ui, spawn)()
        exp = ui._active_experiment
        try:
            before = count(exp)
        except AttributeError as exc:            # scene renamed its list
            _check(False, f"{name}: cannot probe the scene ({exc})")
            continue

        bid, btn, centre = _scene_palette_button(ui)
        if centre is None:
            _check(False, f"{name}: no palette button to test against")
            continue

        # Open hand over the button, then close on it: the machine needs the
        # open->closed transition to fire at all.
        _feed(ui, _hand_at(*centre, curl=0.0))
        _feed(ui, _hand_at(*centre, curl=0.9))

        _check(btn.pressed or btn.selected,
               f"{name}: closing on {bid!r} pressed the button")
        _check(ui._active_experiment is exp,
               f"{name}: ...the experiment is still running")
        _check(count(exp) == before,
               f"{name}: ...and the scene took nothing "
               f"(probe moved by {count(exp) - before})")

    # The other half: the same gesture over empty scene MUST still land.
    for spawn, name, count in SCENES:
        ui = _live_manager()
        ui._set_state("experiments")
        getattr(ui, spawn)()
        exp = ui._active_experiment
        before = count(exp)
        empty = (W * 0.5, H * 0.5)
        _feed(ui, _hand_at(*empty, curl=0.0))
        _feed(ui, _hand_at(*empty, curl=0.9))
        _check(count(exp) > before,
               f"{name}: the same gesture over empty scene still lands "
               f"(+{count(exp) - before})")


def check_reset_ordering():
    """Reset is the other shape of the same rule.

    It changes `state`, so the button-first ordering alone stops the scene
    from ever running that frame. Worth its own check precisely BECAUSE it
    passes for a different reason than everything above.
    """
    print("\n--- a state-changing button (Reset) " + "-" * 33)
    ui = _live_manager()
    ui._set_state("experiments")
    ui._spawn_charges()
    exp = ui._active_experiment
    _bid, _btn, centre = _button_centre(ui, "reset")
    _feed(ui, _hand_at(*centre, curl=0.0))
    _feed(ui, _hand_at(*centre, curl=0.9))
    _check(ui._active_experiment is None and ui.state == "menu",
           "closing on Reset left the experiment")
    _check(len(exp.charges) == 0, "...and dropped no charge on the way out")


def check_hover_alone_is_enough():
    """Rule 1, the hover half: the complaint was also about merely hovering."""
    print("\n--- hovering a button is enough to claim the hand " + "-" * 19)
    ui = _live_manager()
    ui._set_state("experiments")
    ui._spawn_charges()

    _bid, _btn, centre = _scene_palette_button(ui)
    _feed(ui, _hand_at(*centre, curl=0.0), frames=6)
    hid, _machine = gestures.pinch_infos()[0]
    _check(gestures.hand_reserved(hid),
           "an OPEN hand resting on a button is already reserved")

    _check(gestures.pinch_state(hid)[0] is False,
           "pinch_state withholds the closing event from a reserved hand")


def check_drag_survives_a_button():
    """Rule 3: only the EVENT is withheld, never the hold.

    Carrying a charge across the Reset button in the corner must not drop it
    there. This is why the reservation suppresses `pinching` and leaves
    `held` alone.
    """
    print("\n--- a drag survives crossing a button " + "-" * 31)
    ui = _live_manager()
    ui._set_state("experiments")
    ui._spawn_charges()
    exp = ui._active_experiment

    # Place one charge in open space...
    start = (W * 0.5, H * 0.5)
    _feed(ui, _hand_at(*start, curl=0.0))
    _feed(ui, _hand_at(*start, curl=0.9))
    if not _check(len(exp.charges) > 0, "a charge was placed to drag"):
        return
    # ...then OPEN and close again on it. One closing event does one thing:
    # the close that placed the charge cannot also grab it.
    _feed(ui, _hand_at(*start, curl=0.0))
    _feed(ui, _hand_at(*start, curl=0.9))
    _check(exp.grabbed, "a second close on the charge grabbed it")

    # Now carry it, still closed, across the palette AND the Reset button.
    _bid, _btn, centre = _scene_palette_button(ui)
    _feed(ui, _hand_at(*centre, curl=0.9), frames=8)
    _check(ui._active_experiment is not None,
           "crossing a palette button did not press it")
    _bid, _btn, centre = _button_centre(ui, "reset")
    _feed(ui, _hand_at(*centre, curl=0.9), frames=8)
    hid, machine = gestures.pinch_infos()[0]
    _check(gestures.hand_reserved(hid), "the hand is reserved over the button")
    _check(machine.closed, "the hand is still held closed")
    _check(gestures.pinch_state(hid)[1] is True,
           "pinch_state still reports the HOLD for a reserved hand")
    _check(ui._active_experiment is not None,
           "carrying a held object over Reset did not fire it")
    _check(exp.grabbed, "...and the charge is still being dragged")


def check_reservation_is_per_frame():
    """A reservation must not outlive the frame that made it, or a hand that
    once touched a button would be deaf to the scene forever."""
    print("\n--- reservations last exactly one frame " + "-" * 29)
    ui = _live_manager()
    ui._set_state("experiments")
    ui._spawn_charges()
    exp = ui._active_experiment

    _bid, _btn, centre = _scene_palette_button(ui)
    _feed(ui, _hand_at(*centre, curl=0.0), frames=4)
    hid, _m = gestures.pinch_infos()[0]
    _check(gestures.hand_reserved(hid), "reserved while over the button")

    # Move away, still open, then close in open space.
    empty = (W * 0.5, H * 0.5)
    _feed(ui, _hand_at(*empty, curl=0.0), frames=4)
    hid, _m = gestures.pinch_infos()[0]
    _check(not gestures.hand_reserved(hid),
           "released as soon as it leaves the button")
    before = len(exp.charges)
    _feed(ui, _hand_at(*empty, curl=0.9))
    _check(len(exp.charges) > before,
           "and the scene hears it again (+%d)" % (len(exp.charges) - before))


def check_button_lists_agree():
    """`_active_buttons()` feeds update, reserve, to_state and draw. If it
    ever disagreed with what is serialized, the browser would show a button
    the backend does not hit-test — or hit-test one nobody can see."""
    print("\n--- one button list, four consumers " + "-" * 33)
    for setup, label in (
        (lambda ui: None, "menu"),
        (lambda ui: ui._set_state("experiments"), "experiment picker"),
        (lambda ui: (ui._set_state("experiments"), ui._spawn_orbitals()),
         "orbitals (with palette)"),
        (lambda ui: (ui._set_state("experiments"), ui._spawn_slingshot()),
         "slingshot (with speed stepper)"),
    ):
        ui = _live_manager()
        setup(ui)
        ids = [bid for bid, _b in ui._active_buttons()]
        served = [b["id"] for b in ui.to_state()["buttons"]]
        _check(ids == served,
               f"{label}: to_state serves exactly the live buttons "
               f"({len(ids)})")
        _check(len(set(ids)) == len(ids), f"{label}: no duplicate button ids")


def main():
    check_button_beats_scene()
    check_reset_ordering()
    check_hover_alone_is_enough()
    check_drag_survives_a_button()
    check_reservation_is_per_frame()
    check_button_lists_agree()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} failure(s)")
        return 1
    print("UI interaction rules OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
