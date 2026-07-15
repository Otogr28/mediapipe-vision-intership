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


def check_spacetime_physics():
    """Assert the geometry is the textbook one, not something that merely looks
    plausible. These are the claims the config comments make; if a refactor
    breaks one, it should fail here rather than in front of a visitor."""
    import math

    import config as C
    from ui.interactables import _embed_height, _kerr_force_factor

    # 1. The interior cap and the exterior paraboloid must meet with a COMMON
    #    TANGENT at the body's surface [MTW 1973 Box 23.2]: both slopes equal
    #    sqrt(rs/(R - rs)). A mismatch would put a visible crease in the sheet.
    for name, spec in C.ST_MASS_TYPES.items():
        rs = C.ST_RS_PER_MASS * spec["m"]
        R = rs * spec["r_over_rs"]
        if R <= rs * 1.001:
            continue                      # a horizon, not a surface
        h = 1e-4
        inside = (_embed_height(R - h, rs, R) - _embed_height(R - 2 * h, rs, R)) / h
        outside = (_embed_height(R + 2 * h, rs, R) - _embed_height(R + h, rs, R)) / h
        exact = math.sqrt(rs / (R - rs))
        assert abs(inside - exact) < 1e-3, f"{name}: interior slope {inside} != {exact}"
        assert abs(outside - exact) < 1e-3, f"{name}: exterior slope {outside} != {exact}"

    # 2. A black hole must be far deeper than a star, and only IT may have the
    #    vertical throat — the whole point of the palette.
    def depth(spec):
        rs = C.ST_RS_PER_MASS * spec["m"]
        R = rs * spec["r_over_rs"]
        return _embed_height(C.ST_CURV_REACH_PX, rs, R) - _embed_height(max(R, rs), rs, R)

    d_sun = depth(C.ST_MASS_TYPES["sun"])
    d_bh = depth(C.ST_MASS_TYPES["bh"])
    assert d_bh > 3 * d_sun, f"hole ({d_bh:.0f}px) not dramatically deeper than sun ({d_sun:.0f}px)"

    # 3. Mukhopadhyay must collapse to Paczynski-Wiita at zero spin, or the
    #    measured 47 deg/lap precession silently changes meaning.
    for x in (3.0, 6.0, 50.0):
        assert abs(_kerr_force_factor(x, 0.0) - 1.0 / (x - 2.0) ** 2) < 1e-12

    # 4. Pitch is UNCLAMPED on purpose (the user must be able to orbit under
    #    the sheet). Guard against a well-meaning clamp creeping back in.
    assert not hasattr(C, "ST_PITCH_MAX_RAD"), "pitch clamp came back"
    assert not hasattr(C, "ST_PITCH_MIN_RAD"), "pitch clamp came back"
    print("  ok    Spacetime physics (tangency / depth ordering / PW limit / free pitch)")


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
    st._place_mass(W * 0.75, H * 0.35, "bh")       # spinning body: Kerr paths
    st._place_mass(W * 0.25, H * 0.65, "neutron")  # interior cap path
    # Every render/camera branch: 2D sheet, 3D lattice, and the Top snap.
    cases.append(("Spacetime", st, (st._toggle_view, st._toggle_top,
                                    st._toggle_top, st._toggle_view)))

    cases.append(("Puppet", Puppet(W, H), ()))

    failed = []
    try:
        check_spacetime_physics()
    except Exception:
        failed.append('Spacetime physics')
        print('  FAIL  Spacetime physics\n' + traceback.format_exc())
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
