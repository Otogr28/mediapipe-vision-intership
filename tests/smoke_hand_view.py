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


class Cat:
    """A handedness category, the shape `gestures.hand_id()` reads."""

    def __init__(self, name):
        self.category_name = name


class Result:
    def __init__(self, hands, labels=None):
        self.hand_landmarks = hands
        self.hand_world_landmarks = [["world"] for _ in hands]
        labels = labels or (["Left", "Right"][:len(hands)] or ["Left"])
        self.handedness = [[Cat(n)] for n in labels[:len(hands)]]


def check(name, cond, detail=""):
    print("  %-58s %s" % (name, "ok" if cond else "FAIL " + detail))
    if not cond:
        FAIL.append(name)


def hand_at(cx, cy, size=0.1):
    """One 'hand' as four landmarks around (cx, cy), in window coordinates."""
    return [Lm(cx - size, cy - size), Lm(cx + size, cy - size),
            Lm(cx - size, cy + size), Lm(cx + size, cy + size)]


def hand_in(box, fx, fy, size=0.043):
    """A hand standing at FRAME position (fx, fy), as the detector would report
    it: in the coordinates of ``box``, and only if it is inside that window.

    Feeding frame coordinates straight in would be testing nothing — the whole
    job of the remap is the change of coordinates, so the simulation has to
    make the same change in the opposite direction.
    """
    x0, y0, bw, bh = box
    wx = (fx * W - x0) / float(bw)
    wy = (fy * H - y0) / float(bh)
    sx, sy = size * W / float(bw), size * H / float(bh)
    if not (0 <= wx - sx and wx + sx <= 1 and 0 <= wy - sy and wy + sy <= 1):
        return None                          # outside: the model sees nothing
    return [Lm(wx - sx, wy - sy), Lm(wx + sx, wy - sy),
            Lm(wx - sx, wy + sy), Lm(wx + sx, wy + sy)]


def offer(vp, t, hands):
    """Choose a window, report whichever of ``hands`` falls inside it.

    ``hands`` is a list of (frame_x, frame_y, label).
    """
    box = vp.choose(W, H, t)
    found, labels = [], []
    for fx, fy, label in hands:
        lms = hand_in(box, fx, fy)
        if lms is not None:
            found.append(lms)
            labels.append(label)
    return box, vp.remap(Result(found, labels) if found else Result([]), t)


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
    vp.remap(Result([hand_at(0.8, 0.5, 0.04)], ["Right"]), 1)
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

    vp2 = HandViewport()
    vp2.choose(W, H, 1)
    vp2.remap(Result([hand_at(0.02, 0.98, 0.03)]), 1)
    edge = vp2.choose(W, H, 2)
    check("a hand at the corner still gives a legal window",
          edge[0] >= 0 and edge[1] >= 0 and edge[0] + edge[2] <= W
          and edge[1] + edge[3] <= H, str(edge))


def check_two_hands():
    """The reason this layer has slots at all.

    Arms apart at exhibit distance put the hands ~470 px apart in a 1280-wide
    frame. One window around their union pads out past the whole frame, which
    is exactly the full-frame case that finds nothing — so each hand gets its
    own window and they take turns.
    """
    print("two hands (the T-pose geometry: 0.37 and 0.90 of the frame)")
    HANDS = [(0.37, 0.49, "Left"), (0.90, 0.48, "Right")]
    vp = HandViewport(scale=0.5, seek_every=3, max_hands=2)
    for t in range(1, 30):
        offer(vp, t, HANDS)
        if vp.to_state()["tracked"] == 2:
            break
    check("both hands are found and tracked separately",
          vp.to_state()["tracked"] == 2, str(vp.to_state()))
    check("within a second of frames", t < 30, "took %d" % t)

    boxes, targets = [], []
    for t in range(100, 106):
        box, _out = offer(vp, t, HANDS)
        boxes.append(box)
        targets.append(vp.last_target)
    check("the turn alternates between the two hands",
          set(targets) == {"hand0", "hand1"}, str(targets))
    check("no seek turns once both hands are tracked",
          "scan" not in targets, str(targets))
    check("every window is well under the full frame",
          all(b[2] <= W * 0.65 for b in boxes), str([b[2] for b in boxes]))
    centres = sorted({round((b[0] + b[2] / 2.0) / W, 2) for b in boxes})
    check("the two windows sit on the two hands", len(centres) == 2
          and abs(centres[0] - 0.37) < 0.10 and abs(centres[1] - 0.90) < 0.10,
          str(centres))

    # The published result carries BOTH, even though this frame's window only
    # looked at one of them.
    _box, out = offer(vp, 200, HANDS)
    check("both hands are published from one window's result",
          out is not None and len(out.hand_landmarks) == 2,
          str(out and len(out.hand_landmarks)))
    labels = [h[0].category_name for h in out.handedness]
    check("each keeps its own handedness", sorted(labels) == ["Left", "Right"],
          str(labels))
    check("world landmarks stay aligned with the hands",
          len(out.hand_world_landmarks) == 2)

    # And they are published where they actually stand.
    got = sorted(round(sum(lm.x for lm in h) / len(h), 2)
                 for h in out.hand_landmarks)
    check("both land on their real frame positions",
          abs(got[0] - 0.37) < 0.03 and abs(got[1] - 0.90) < 0.03, str(got))

    # A union window would have been this wide — the thing being avoided.
    union = (0.90 - 0.37) * W + 0.043 * 2 * W
    check("(for the record) their union padded 2.5x exceeds the frame",
          union * 2.5 > W, "%.0f px" % (union * 2.5))


def check_identity():
    print("identity (a slot must not swap hands)")
    # Close together, and a window floor wide enough to hold both, so the
    # match is what decides the answer rather than the framing.
    HANDS = [(0.44, 0.5, "Left"), (0.58, 0.5, "Right")]
    vp = HandViewport(max_hands=2, min_scale=0.6)
    box, _ = offer(vp, 1, HANDS)
    check("two hands from one window", vp.to_state()["tracked"] == 2,
          str(vp.to_state()))

    # Report them in the OTHER order: handedness must win over list position.
    box = vp.choose(W, H, 2)
    a = hand_in(box, 0.60, 0.5)
    b = hand_in(box, 0.42, 0.5)
    check("both hands are inside this window", a is not None and b is not None)
    out = vp.remap(Result([a, b], ["Right", "Left"]), 2)
    xs = [sum(lm.x for lm in h) / len(h) for h in out.hand_landmarks]
    labels = [h[0].category_name for h in out.handedness]
    left = xs[labels.index("Left")]
    right = xs[labels.index("Right")]
    check("Left stays on the left hand after a reordered result",
          abs(left - 0.42) < 0.03, "%.2f" % left)
    check("Right stays on the right one", abs(right - 0.60) < 0.03,
          "%.2f" % right)

    # With no handedness at all, position has to carry it.
    vp2 = HandViewport(max_hands=2, min_scale=0.6)
    box = vp2.choose(W, H, 1)
    r = Result([hand_in(box, 0.44, 0.5), hand_in(box, 0.58, 0.5)])
    r.handedness = []
    vp2.remap(r, 1)
    check("two hands tracked without handedness",
          vp2.to_state()["tracked"] == 2, str(vp2.to_state()))
    box = vp2.choose(W, H, 2)
    r = Result([hand_in(box, 0.60, 0.5), hand_in(box, 0.42, 0.5)])
    r.handedness = []
    out = vp2.remap(r, 2)
    check("still two, matched by position alone",
          len(out.hand_landmarks) == 2, str(len(out.hand_landmarks)))


def check_motion():
    print("motion (hands do not hold still)")
    vp = HandViewport(pad=2.0, grow=1.7, lost_frames=5, max_hands=1)
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
    box = vp.choose(W, H, 7)
    check("after enough misses the slot is dropped for a scan",
          vp.to_state()["tracked"] == 0
          and box in HandViewport(scale=vp.scale)._positions(W, H), str(box))

    # A miss on ONE hand's window must not retire the other.
    vp2 = HandViewport(lost_frames=2, max_hands=2)
    vp2.choose(W, H, 1)
    vp2.remap(Result([hand_at(0.3, 0.5, 0.04), hand_at(0.7, 0.5, 0.04)],
                     ["Left", "Right"]), 1)
    for t in range(2, 8):
        vp2.choose(W, H, t)
        if vp2.last_target == "hand0":
            vp2.remap(Result([]), t)        # only hand0 goes missing
        else:
            vp2.remap(Result([hand_at(0.7, 0.5, 0.04)], ["Right"]), t)
    check("losing one hand leaves the other tracked",
          vp2.to_state()["tracked"] == 1, str(vp2.to_state()))

    # The same packet stays newest for several render frames; ingesting it
    # again must not count as another miss.
    vp3 = HandViewport(lost_frames=2)
    vp3.choose(W, H, 1)
    vp3.remap(Result([hand_at(0.5, 0.5, 0.04)]), 1)
    vp3.choose(W, H, 2)
    empty = Result([])
    for _ in range(6):
        vp3.remap(empty, 2)                 # same timestamp, six render frames
    check("a repeated result is ingested once, not once per frame",
          vp3.to_state()["tracked"] == 1, str(vp3.to_state()))


def check_staleness():
    print("staleness")
    vp = HandViewport(max_hands=2, hold_ms=400)
    vp.choose(W, H, 1000)
    vp.remap(Result([hand_at(0.3, 0.5, 0.04), hand_at(0.7, 0.5, 0.04)],
                    ["Left", "Right"]), 1000)
    t = 1100
    vp.choose(W, H, t)
    out = vp.remap(Result([hand_at(0.3, 0.5, 0.04)], ["Left"]), t)
    check("a hand held between its turns is still published",
          len(out.hand_landmarks) == 2, str(len(out.hand_landmarks)))
    t = 1600                                 # 600 ms since the other was seen
    vp.choose(W, H, t)
    out = vp.remap(Result([hand_at(0.3, 0.5, 0.04)], ["Left"]), t)
    check("a hand not seen for hold_ms drops out",
          len(out.hand_landmarks) == 1, str(len(out.hand_landmarks)))


def check_remap():
    print("remap (window coordinates back to frame coordinates)")
    vp = HandViewport(max_hands=1)
    vp.choose(W, H, 1)
    vp.remap(Result([hand_at(0.8, 0.5, 0.04)]), 1)
    box = vp.choose(W, H, 2)
    out = vp.remap(Result([[Lm(0.5, 0.5)]]), 2)
    px = out.hand_landmarks[0][0].x * W
    py = out.hand_landmarks[0][0].y * H
    check("centre of the window is the centre of the window",
          abs(px - (box[0] + box[2] / 2.0)) < 1.5
          and abs(py - (box[1] + box[3] / 2.0)) < 1.5,
          "(%.0f,%.0f) vs %s" % (px, py, box))

    vp2 = HandViewport(max_hands=1)
    vp2.choose(W, H, 1)
    vp2.remap(Result([hand_at(0.8, 0.5, 0.04)]), 1)
    box = vp2.choose(W, H, 2)
    out = vp2.remap(Result([[Lm(0.0, 0.0), Lm(1.0, 1.0)]]), 2)
    a, b = out.hand_landmarks[0]
    check("window corners map to the window's corners",
          abs(a.x * W - box[0]) < 1.5 and abs(a.y * H - box[1]) < 1.5
          and abs(b.x * W - (box[0] + box[2])) < 1.5
          and abs(b.y * H - (box[1] + box[3])) < 1.5)

    # A result whose window has aged out cannot be placed anywhere honest.
    vp3 = HandViewport()
    vp3.choose(W, H, 1)
    vp3.remap(Result([hand_at(0.5, 0.5, 0.04)]), 1)
    for t in range(2, 60):
        vp3.choose(W, H, t)
    before = vp3.to_state()["tracked"]
    vp3.remap(Result([hand_at(0.1, 0.1)]), 0)
    check("a result older than the window table is ignored, not misplaced",
          vp3.to_state()["tracked"] == before)

    check("z is scaled with x, not left in window units",
          abs(_z_scale() - 1.0) > 1e-6, "%.4f" % _z_scale())
    check("no hands tracked publishes nothing",
          HandViewport().remap(None, None) is None)


def _z_scale():
    vp = HandViewport(max_hands=1)
    vp.choose(W, H, 1)
    vp.remap(Result([hand_at(0.5, 0.5, 0.04)]), 1)
    vp.choose(W, H, 2)
    out = vp.remap(Result([[Lm(0.5, 0.5, 1.0)]]), 2)
    return out.hand_landmarks[0][0].z


def main():
    check_scan()
    check_lock()
    check_two_hands()
    check_identity()
    check_motion()
    check_staleness()
    check_remap()
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
