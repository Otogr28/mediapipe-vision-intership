"""Smoke-test every experiment's FULL public surface.

    uv run python tests/smoke_scenes.py

Why this exists: a NameError in `Spacetime.to_state()` (a config constant used
but never imported) reached the Jetson because the pre-push check called
`update()` and nothing else. In web mode `to_state()` runs every frame inside
`main.py`'s resilient try/except — so the failure does not crash the process,
it silently stops the state publish and FREEZES the kiosk for anyone in that
experiment, with no working Reset button to escape. Importing is not enough of
a check; each entry point has to actually run.

So: for every scene, call each of `update()` / `to_state()` / `draw()` — the
three things `main.py` calls — plus any mode toggle that swaps a render path,
since an unexercised branch is exactly where the last one hid.

Deliberately plain `python` with no pytest dependency: this must also run on the
Jetson's system Python 3.10 (`ssh jetson@... 'cd ~/HalLMediaPipe && python3
tests/smoke_scenes.py'`), which is where the version/wheel differences from the
laptop's 3.12 would show up.
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

import numpy as np  # noqa: E402

from ui.interactables import (BlackHole, BouncingSphere, Charges,  # noqa: E402
                              Orbitals, Puppet, SixSevenCounter, Slingshot,
                              Spacetime, Waves)

W, H = 1280, 720


def _exercise(name, obj, frames=30, toggles=()):
    """Run one scene through everything main.py would call.

    `toggles` are zero-arg callables that flip a render path (e.g. Spacetime's
    2D sheet <-> 3D lattice); each is applied and the whole surface re-run, so
    both branches get covered.
    """
    def surface(tag):
        for _ in range(frames):
            obj.update(None, None)
        state = obj.to_state()
        assert isinstance(state, dict) and "type" in state, f"{tag}: bad state"
        # to_state must be JSON-encodable — the SSE endpoint json.dumps() it.
        import json
        json.dumps(state)
        frame = np.full((H, W, 3), 120, np.uint8)
        obj.draw(frame)
        return state

    surface(name)
    for i, toggle in enumerate(toggles):
        toggle()
        surface(f"{name}[toggle {i}]")
    return True


def main():
    cases = []

    sphere = BouncingSphere(W, H)
    cases.append(("BouncingSphere", sphere, ()))

    # BlackHole takes a GL renderer; None is the web-mode path (no GL context).
    cases.append(("BlackHole", BlackHole(W, H, None), ()))
    cases.append(("SixSevenCounter", SixSevenCounter(W, H), ()))
    cases.append(("Slingshot", Slingshot(W, H), ()))

    orb = Orbitals(W, H)
    orb._spawn(W * 0.5, H * 0.5, 0.0, 0.0, "star")
    orb._spawn(W * 0.5 + 180, H * 0.5, 0.0, 60.0, "planet")
    cases.append(("Orbitals", orb, ()))

    waves = Waves(W, H)
    waves._place(W * 0.4, H * 0.5)
    waves._place(W * 0.6, H * 0.5)
    cases.append(("Waves", waves, ()))

    chg = Charges(W, H)
    chg._preset_dipole()
    cases.append(("Charges", chg, ()))

    st = Spacetime(W, H)
    st._preset_precession()
    st._place_mass(W * 0.75, H * 0.35, "bh")     # a spinning body: Kerr paths
    # Both render modes: the 2D sheet AND the 3D volumetric lattice.
    cases.append(("Spacetime", st, (st._toggle_view, st._toggle_view)))

    cases.append(("Puppet", Puppet(W, H), ()))

    failed = []
    for name, obj, toggles in cases:
        try:
            _exercise(name, obj, toggles=toggles)
            print(f"  ok    {name}")
        except Exception:
            failed.append(name)
            print(f"  FAIL  {name}\n{traceback.format_exc()}")

    print(f"\n{len(cases) - len(failed)}/{len(cases)} scenes ok")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
