"""Smoke test for the detector viewport (src/hand_view.py).

Scope, deliberately narrow: this checks ARITHMETIC. Which window is chosen,
whether a scan covers the frame, whether a lock follows the hand, whether a
lost hand widens the search instead of being dropped, and whether landmarks
found in a window land back on the right pixels of the full frame.

It contains no images at all — not a photograph, not a generated one. Whether
the model can SEE a hand is not a question a made-up picture can answer, and
trying cost this project a session: image processing tuned against an invented
scene passed its own test and made the exhibit worse. That question is settled
by `tests/bench_hands.py`, which runs the real detector over real frames from
the real camera on the Jetson.

Like the rest of `tests/`, a plain `python` script, so it runs on the Jetson's
system 3.10 as well as the laptop's 3.12.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from hand_view import HandViewport  # noqa: E402

W, H = 1280, 720
FAIL = []


class Lm:
    """The three attributes the remap reads off a landmark."""

    def __init__(self, x, y, z=0.0):
        self.x = x
        self.y = y
        self.z = z
        self.visibility = None
        self.presence = None


class Result:
    def __init__(self, hands):
        self.hand_landmarks = hands
        self.hand_world_landmarks = [["world"]]
        self.handedness = [["Left"]]


def check(name, cond, detail=""):
    print("  %-58s %s" % (name, "ok" if cond else "FAIL " + detail))
    if not cond:
        FAIL.append(name)


def hand_at(cx, cy, size=0.1):
    """One 'hand' as four landmarks around (cx, cy), in window coordinates."""
    return [Lm(cx - size, cy - size), Lm(cx + size, cy - size),
            Lm(cx - size, cy + size), Lm(cx + size, cy + size)]


def check_scan():
    print("scan (nothing tracked)")
    vp = HandViewport(scale=0.5)
    boxes = [vp.choose(W, H, t) for t in range(10)]
    check("first position is the whole frame", boxes[0] == (0, 0, W, H),
          str(boxes[0]))
    tiles = boxes[1:10]
    check("then nine tiles", len(tiles) == 9 and all(
        b[2] == W // 2 and b[3] == H // 2 for b in tiles), str(tiles[:2]))
    # Every pixel of the frame has to fall inside some tile, or a hand standing
    # there is invisible for as long as the visitor keeps it there.
    covered = all(
        any(x0 <= px < x0 + bw and y0 <= py < y0 + bh
            for x0, y0, bw, bh in tiles)
        for px in range(0, W, 40) for py in range(0, H, 40))
    check("the tiles cover the whole frame", covered)
    # 50% overlap: a hand narrower than half a tile fits wholly in one of them
    # wherever it sits. Checked at the worst case, a tile seam.
    seam_x = W // 4
    hand_w = W // 5
    fits = any(x0 <= seam_x - hand_w // 2 and seam_x + hand_w // 2 <= x0 + bw
               for x0, _y0, bw, _bh in tiles)
    check("a hand on a seam fits wholly inside some tile", fits)
    check("the scan wraps round", vp.choose(W, H, 99) == boxes[0])


def check_lock():
    print("lock (a hand was found)")
    vp = HandViewport(scale=0.5, pad=2.5, min_scale=0.35)
    vp.choose(W, H, 1)                      # full frame
    vp.remap(Result([hand_at(0.8, 0.5, 0.04)]), 1)
    box = vp.choose(W, H, 2)
    check("the window shrinks onto the hand", box[2] < W and box[3] < H,
          str(box))
    cx = box[0] + box[2] / 2.0
    check("and is centred on it", abs(cx - 0.8 * W) < 0.06 * W, "cx=%.0f" % cx)
    check("never below the floor", box[2] >= W * 0.35 - 1, str(box))
    check("keeps the frame's aspect ratio",
          abs(box[2] / float(box[3]) - W / float(H)) < 0.02,
          "%.3f" % (box[2] / float(box[3])))
    check("stays inside the frame",
          box[0] >= 0 and box[1] >= 0
          and box[0] + box[2] <= W and box[1] + box[3] <= H, str(box))

    # A hand at the very edge: the window has to clamp without shrinking, or
    # the landmark model gets a window it cannot fill.
    vp2 = HandViewport()
    vp2.choose(W, H, 1)
    vp2.remap(Result([hand_at(0.02, 0.98, 0.03)]), 1)
    edge = vp2.choose(W, H, 2)
    check("a hand at the corner still gives a legal window",
          edge[0] >= 0 and edge[1] >= 0 and edge[0] + edge[2] <= W
          and edge[1] + edge[3] <= H, str(edge))


def check_motion():
    print("motion (hands do not hold still)")
    vp = HandViewport(pad=2.0, grow=1.7, lost_frames=5)
    vp.choose(W, H, 1)
    vp.remap(Result([hand_at(0.5, 0.5, 0.04)]), 1)
    widths = []
    for t in range(2, 7):
        widths.append(vp.choose(W, H, t)[2])
        vp.remap(Result([]), t)             # a miss: the hand moved away
    check("each miss widens the search", all(
        b > a for a, b in zip(widths, widths[1:])) or widths[-1] == W,
        str(widths))
    check("it reaches the whole frame rather than stalling",
          widths[-1] >= W * 0.9, str(widths))
    # The scan RESUMES where it left off rather than restarting at the full
    # frame — the full frame is the position that just failed to find anything.
    box = vp.choose(W, H, 7)
    check("after enough misses the lock is dropped for a scan",
          vp.to_state()["mode"] == "scan"
          and box in HandViewport(scale=vp.scale)._positions(W, H), str(box))

    # A hand that keeps being found must NOT drift the window away from it.
    vp3 = HandViewport()
    vp3.choose(W, H, 1)
    for t, cx in enumerate([0.5, 0.55, 0.62, 0.70], start=1):
        vp3.remap(Result([hand_at(0.5, 0.5, 0.04)]), t)
        box = vp3.choose(W, H, t + 1)
        # The hand is reported at the window's centre each time, so the window
        # should keep sitting where it is and never walk out of the frame.
        check("tracking window %d stays legal" % t,
              box[0] >= 0 and box[0] + box[2] <= W, str(box))


def check_remap():
    print("remap (window coordinates back to frame coordinates)")
    vp = HandViewport()
    vp.choose(W, H, 1)
    vp.remap(Result([hand_at(0.8, 0.5, 0.04)]), 1)
    box = vp.choose(W, H, 2)
    # A landmark dead centre of the window is that window's centre pixel.
    out = vp.remap(Result([[Lm(0.5, 0.5)]]), 2)
    px = out.hand_landmarks[0][0].x * W
    py = out.hand_landmarks[0][0].y * H
    check("centre of the window is the centre of the window",
          abs(px - (box[0] + box[2] / 2.0)) < 1.5
          and abs(py - (box[1] + box[3] / 2.0)) < 1.5,
          "(%.0f,%.0f) vs %s" % (px, py, box))
    # Corners, so a sign error cannot hide behind symmetry.
    out = vp.remap(Result([[Lm(0.0, 0.0), Lm(1.0, 1.0)]]), 2)
    a, b = out.hand_landmarks[0]
    check("window corners map to the window's corners",
          abs(a.x * W - box[0]) < 1.5 and abs(a.y * H - box[1]) < 1.5
          and abs(b.x * W - (box[0] + box[2])) < 1.5
          and abs(b.y * H - (box[1] + box[3])) < 1.5)
    check("world landmarks and handedness pass through untouched",
          out.hand_world_landmarks == [["world"]]
          and out.handedness == [["Left"]])

    # The full-frame window is the identity, and must not cost a rebuild.
    vp4 = HandViewport()
    vp4.choose(W, H, 1)
    same = Result([hand_at(0.5, 0.5)])
    check("a full-frame window returns the result unchanged",
          vp4.remap(same, 1) is same)

    # A result whose window has aged out cannot be placed anywhere honest.
    vp5 = HandViewport()
    for t in range(40):
        vp5.choose(W, H, t)
    check("a result older than the window table is dropped",
          vp5.remap(Result([hand_at(0.5, 0.5)]), 0) is None)


def check_disabled_path():
    print("off")
    check("z is scaled with x, not left in window units",
          abs(_z_scale() - 1.0) > 1e-6, "%.4f" % _z_scale())


def _z_scale():
    vp = HandViewport()
    vp.choose(W, H, 1)
    vp.remap(Result([hand_at(0.5, 0.5, 0.04)]), 1)
    vp.choose(W, H, 2)
    out = vp.remap(Result([[Lm(0.5, 0.5, 1.0)]]), 2)
    return out.hand_landmarks[0][0].z


def main():
    check_scan()
    check_lock()
    check_motion()
    check_remap()
    check_disabled_path()
    print()
    if FAIL:
        print("FAILED: %d" % len(FAIL))
        for name in FAIL:
            print("  - %s" % name)
        return 1
    print("all hand_view geometry checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
