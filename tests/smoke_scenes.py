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
                              Magnets, Orbitals, Puppet, SchrodingerCat,
                              SixSevenCounter, Slingshot, Spacetime, Waves)

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
    from ui.interactables import (_C_SCREEN, Spacetime, _embed_height,
                                  _kerr_force_factor)
    G, c = C.ST_ORB_G, _C_SCREEN

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
    d_neu = depth(C.ST_MASS_TYPES["neutron"])
    d_bh = depth(C.ST_MASS_TYPES["bh"])
    # Ordering, not a magic ratio: compactness is what deepens the well.
    assert d_sun < d_neu < d_bh, f"depth ordering wrong: {d_sun:.0f}/{d_neu:.0f}/{d_bh:.0f}"
    assert d_bh > 2.5 * d_sun, f"hole ({d_bh:.0f}px) not much deeper than sun ({d_sun:.0f}px)"

    # The claim that actually distinguishes them is the THROAT: a hole's sheet
    # goes vertical at its horizon, a star's is a smooth cap. Assert the kind
    # difference, not a tuned number — depth scales with sqrt(rs) and moves
    # whenever the regime is retuned, but this never should.
    def surface_slope(spec):
        rs = C.ST_RS_PER_MASS * spec["m"]
        R = max(rs * spec["r_over_rs"], rs)
        r0 = R + 1e-3
        h = 1e-3
        return (_embed_height(r0 + h, rs, R) - _embed_height(r0, rs, R)) / h

    assert surface_slope(C.ST_MASS_TYPES["sun"]) < 1.0, "sun grew a throat"
    assert surface_slope(C.ST_MASS_TYPES["bh"]) > 50.0, "hole lost its vertical throat"

    # 3. Mukhopadhyay must collapse to Paczynski-Wiita at zero spin, or the
    #    measured 47 deg/lap precession silently changes meaning.
    for x in (3.0, 6.0, 50.0):
        assert abs(_kerr_force_factor(x, 0.0) - 1.0 / (x - 2.0) ** 2) < 1e-12

    # 4. The GW drag must remove energy at EXACTLY Peters' rate and be
    #    equal-and-opposite (momentum conserved). This is the design claim.
    from ui.interactables import _C_SCREEN, Spacetime
    G, c = C.ST_ORB_G, _C_SCREEN
    for a0 in (160.0, 300.0):
        st = Spacetime(1280, 720)
        m1 = st._place_mass(640.0, 360.0, "bh")
        m1.spin = 0.0
        m1.vx = m1.vy = 0.0
        m2 = st._place_mass(640.0 + a0, 360.0, "bh")
        m2.spin = 0.0
        M = m1.m + m2.m
        vrel = math.sqrt(G * M / a0)
        m2.vx, m2.vy = 0.0, vrel * m1.m / M
        m1.vx, m1.vy = 0.0, -vrel * m2.m / M
        for b in st.bodies():
            b.ax = b.ay = 0.0
        st._gw_drag(m1, m2, a0)
        work = (m1.ax * m1.m * m1.vx + m1.ay * m1.m * m1.vy
                + m2.ax * m2.m * m2.vx + m2.ay * m2.m * m2.vy)
        p_peters = (32.0 / 5.0) * G ** 4 * (m1.m * m2.m) ** 2 * M / (c ** 5 * a0 ** 5)
        assert abs(-work - p_peters) / p_peters < 1e-9, "GW drag off Peters' rate"
        net = (m1.ax * m1.m + m2.ax * m2.m, m1.ay * m1.m + m2.ay * m2.m)
        assert abs(net[0]) < 1e-6 and abs(net[1]) < 1e-6, "GW drag breaks momentum"

    # 5. A hole-hole merger radiates ~5% of the total mass and conserves the rest.
    st = Spacetime(1280, 720)
    a = st._place_mass(500.0, 360.0, "bh")
    # Place the second one just inside contact, derived from the bodies rather
    # than hardcoded — rs per unit mass is a regime knob and has moved before.
    b = st._place_mass(500.0 + max(a.r_horizon, a.r_body), 360.0, "bh")
    b.vx = b.vy = 0.0
    st._merge_masses()
    assert len(st.masses) == 1, "horizons touching did not merge"
    assert abs(st.masses[0].m - 8.0 * (1 - C.ST_MERGE_GW_MASS_LOSS)) < 1e-9

    # 6. EIH (1PN) must converge to the EXACT GR perihelion precession,
    #    dphi = 6*pi*G*M/(c^2 a (1-e^2)) — the Mercury formula. This is the
    #    claim that the dynamics are relativistic and not merely plausible.
    import ui.interactables as _I
    from ui.interactables import _Orbiter
    gw_was = _I.ST_GW_ENABLED
    _I.ST_GW_ENABLED = False          # isolate the conservative sector
    try:
        a0 = 600.0
        st = Spacetime(1280, 720)
        host = st._place_mass(640.0, 360.0, "bh")
        host.spin = 0.0
        host.vx = host.vy = 0.0
        vp = math.sqrt(G * host.m / a0)
        o = _Orbiter(999, 640.0 + a0, 360.0, 0.0, vp, m=1e-6)
        st.orbiters.append(o)
        st._accelerate()
        angs, prev_r, falling = [], None, False
        for _ in range(int(600 / C.ST_PHYS_DT)):
            st._step(C.ST_PHYS_DT)
            if not st.orbiters:
                break
            r = math.hypot(o.x - host.x, o.y - host.y)
            if prev_r is not None:
                if r > prev_r and falling:
                    angs.append(math.atan2(o.y - host.y, o.x - host.x))
                    if len(angs) >= 4:
                        break
                falling = r < prev_r
            prev_r = r
        assert len(angs) >= 3, "orbit did not complete enough laps"
        d = [((angs[i + 1] - angs[i] + math.pi) % (2 * math.pi)) - math.pi
             for i in range(len(angs) - 1)]
        meas = sum(d) / len(d)
        exact = 6 * math.pi * G * host.m / (c * c * a0)
        err = abs(meas - exact) / exact
        assert err < 0.05, f"EIH precession {math.degrees(meas):.2f} vs GR {math.degrees(exact):.2f} ({err*100:.1f}%)"
    finally:
        _I.ST_GW_ENABLED = gw_was

    # 7. Pitch is UNCLAMPED on purpose (the user must be able to orbit under
    #    the sheet). Guard against a well-meaning clamp creeping back in.
    assert not hasattr(C, "ST_PITCH_MAX_RAD"), "pitch clamp came back"
    assert not hasattr(C, "ST_PITCH_MIN_RAD"), "pitch clamp came back"

    # 8. A body that leaves the renderable patch is removed — MASSES included
    #    (an off-screen mass would keep pulling the scene with no visible
    #    cause), except a grabbed one, which the hand pins on-screen.
    st = Spacetime(1280, 720)
    st._place_mass(640.0, 360.0, "sun")
    far = st._place_mass(840.0, 360.0, "neutron")
    far.x = 640.0 + 1280 * C.ST_PRUNE_MARGIN * 0.5 + 10.0
    st._prune()
    assert [m.kind for m in st.masses] == ["sun"], "off-screen mass not pruned"
    st._grab_mass = st.masses[0]
    st.masses[0].x = -9999.0
    st._prune()
    assert st.masses, "grabbed mass must never be pruned"

    print("  ok    Spacetime physics (tangency / depth / PW limit / GW rate /"
          " momentum / merger / EIH-vs-GR precession / free pitch /"
          " off-screen prune)")


def check_magnets_physics():
    """Assert the field model and the induction behave as the config MAG_*
    block claims: exact 2D magnetostatics (far field = 2D dipole), zero EMF
    for a resting magnet, and Lenz-sign current that flips with motion."""
    import math
    import time as _time

    from config import MAG_HALF_H_PX, MAG_HALF_LEN_PX, MAG_TYPES  # noqa: E402

    m = Magnets(W, H)
    m.clear()
    mg = m._place(W * 0.35, H * 0.5, "sn")

    # Far field converges to the 2D dipole with moment M * (2a)(2b):
    # B = m_dip/(2 pi r^2) * (2cos^2-1, 2 sin cos) in the bar's frame.
    m_dip = MAG_TYPES["sn"]["m"] * (2 * MAG_HALF_LEN_PX) * (2 * MAG_HALF_H_PX)
    for ang in (0.3, 1.2, 2.4, 4.0):
        r = 9 * MAG_HALF_LEN_PX
        px = mg.x + r * math.cos(ang)
        py = mg.y + r * math.sin(ang)
        bx, by = m.field_at(px, py)
        c, s = math.cos(ang), math.sin(ang)
        dx = m_dip / (2 * math.pi * r * r) * (2 * c * c - 1)
        dy = m_dip / (2 * math.pi * r * r) * (2 * s * c)
        err = math.hypot(bx - dx, by - dy) / math.hypot(dx, dy)
        assert err < 0.02, f"far field vs 2D dipole off by {err:.1%} at {ang}"

    # Field lines exit the N face and run S->N inside: Bx > 0 just outside
    # BOTH pole faces and inside the bar (m > 0 means N on the right).
    for px in (mg.x + MAG_HALF_LEN_PX + 10, mg.x - MAG_HALF_LEN_PX - 10, mg.x):
        bx, _ = m.field_at(px, mg.y)
        assert bx > 0, f"Bx must point +x on the axis (got {bx} at {px})"

    # A resting magnet induces nothing.
    for _ in range(12):
        m.update(None, None)
        _time.sleep(0.01)
    assert abs(m._cur) < 0.05, f"resting magnet shows current {m._cur}"

    # Motion induces; reversing the motion reverses the sign (Lenz).
    def sweep(step):
        for _ in range(18):
            mg.x += step
            m.update(None, None)
            _time.sleep(0.01)
        return m._cur

    toward = sweep(+12)
    away = sweep(-12)
    assert abs(toward) > 0.1, f"approach induced ~nothing ({toward})"
    assert toward * away < 0, f"no Lenz sign flip ({toward} vs {away})"
    print("  ok    Magnets physics (far field = 2D dipole / axis Bx sign /"
          " rest EMF ~ 0 / Lenz sign flip)")


def check_schrodinger_logic():
    """Walk the full measurement cycle deterministically (no hands: the owner
    latch reads pinch_state(<unknown id>) -> released, which is exactly the
    drop / fire edge)."""
    import json
    import math
    import random

    sc = SchrodingerCat(W, H)
    assert sc.phase == "place"

    # Drop the cat over the box -> lid closes, phase arms.
    bx, by, bw, bh = sc.box
    sc.cat_x, sc.cat_y = bx + bw / 2, by + bh / 2
    sc._grabbed, sc._grab_hand = True, "ghost-hand"
    sc.update(None, None)
    assert sc.phase == "armed" and not sc._grabbed

    # The gun is pre-aimed: muzzle level with the Geiger tube, horizontal
    # shot. Pulling the trigger fires exactly one particle + the recoil kick.
    assert abs(sc.muzzle[1] - sc.geiger[1]) < 1e-6
    sc._fire()
    assert sc.particle is not None and sc.recoil == 1.0
    vx, vy = sc.particle[2], sc.particle[3]
    assert vx > 0 and abs(vy) < 1e-6, "shot is not horizontal at the tube"

    # The particle flies muzzle -> Geiger and arming ignores re-triggers
    # while it is in flight; arrival = superposition (nobody looked).
    for _ in range(600):
        sc.update(None, None)
        if sc.phase == "superposed":
            break
    assert sc.phase == "superposed", "particle never reached the Geiger tube"
    assert sc.particle is None
    for _ in range(80):                    # recoil decays back to zero
        sc.update(None, None)
    assert sc.recoil == 0.0

    # Collapse both branches of the coin; tally accumulates across runs.
    real_random = random.random
    try:
        random.random = lambda: 0.0        # < p_alive -> alive
        sc._collapse()
        assert sc.phase == "revealed" and sc.outcome == "alive"
        sc._new_run()
        assert sc.phase == "place" and sc.outcome is None
        random.random = lambda: 0.999      # >= p_alive -> dead
        sc._collapse()
        assert sc.outcome == "dead"
    finally:
        random.random = real_random
    assert sc.tally == {"alive": 1, "dead": 1}

    # Every phase serializes (captions included) and draws.
    frame_shape = (H, W, 3)
    for phase, outcome in (("place", None), ("armed", None),
                           ("superposed", None), ("revealed", "alive"),
                           ("revealed", "dead")):
        sc.phase, sc.outcome = phase, outcome
        state = sc.to_state()
        json.dumps(state)
        assert state["caption"], f"no caption in {phase}"
        frame = np.full(frame_shape, 120, np.uint8)
        sc.draw(frame)

    print("  ok    SchrodingerCat logic (drop-in-box / trigger fire+recoil /"
          " Geiger hit / both collapse branches / tally / all phases"
          " serialize+draw)")


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

    mag = Magnets(W, H)
    mag._place(W * 0.25, H * 0.75, "ns")   # both orientations render
    cases.append(("Magnets", mag, ()))

    st = Spacetime(W, H)
    st._preset_precession()
    st._place_mass(W * 0.75, H * 0.35, "bh")       # spinning body: Kerr paths
    st._place_mass(W * 0.25, H * 0.65, "neutron")  # interior cap path
    # Every render/camera branch: 2D sheet, 3D lattice, and the Top snap.
    cases.append(("Spacetime", st, (st._toggle_view, st._toggle_top,
                                    st._toggle_top, st._toggle_view)))

    cases.append(("SchrodingerCat", SchrodingerCat(W, H), ()))
    cases.append(("Puppet", Puppet(W, H), ()))

    failed = []
    try:
        check_spacetime_physics()
    except Exception:
        failed.append('Spacetime physics')
        print('  FAIL  Spacetime physics\n' + traceback.format_exc())
    try:
        check_magnets_physics()
    except Exception:
        failed.append('Magnets physics')
        print('  FAIL  Magnets physics\n' + traceback.format_exc())
    try:
        check_schrodinger_logic()
    except Exception:
        failed.append('SchrodingerCat logic')
        print('  FAIL  SchrodingerCat logic\n' + traceback.format_exc())
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
