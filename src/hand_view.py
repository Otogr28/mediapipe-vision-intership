"""Feed the hand detector a WINDOW of the frame instead of the whole frame.

This is the fix for the exhibit's real problem, and the problem turned out not
to be the one everybody assumed. The camera looks down a corridor at a wall of
windows, so "the model cannot find the hand" read as a lighting problem, and
two rounds of work went into exposure. Measured on the exhibit's own frames
(`tests/bench_hands.py` over `~/hall-testframes`, the real GPU pipeline on the
Jetson), the numbers say something else:

    detector input          hand width / frame width    hands found
    full frame 1280x720             8.6 %                  1 / 12
    crop to 1024                   10.7 %                  9 / 12
    crop to 853                    12.9 %                  8 / 12
    crop to 512                    21.5 %                 12 / 12

Same pixels, same exposure, same contrast — only the hand's SHARE of the frame
changed, and detection went from nothing to everything. The hand that reaches
12/12 is the one against the window, the case that was supposed to be hopeless.
Contrast enhancement (`preprocess.py`) was measured on the same set and did not
help at any setting.

The cause is structural: the palm detector resizes whatever it is given to
192x192, so a hand 110 px wide in a 1280-wide frame arrives about 16 px across,
under what the model can find. Halving the field halves that divisor.

The visitor still sees the full camera picture — `main.py` keeps the untouched
frame for the sink and only the DETECTOR gets the window. This is not the
digital crop the operator ruled out, which changed what the exhibit looks like.

How the window is chosen, and why:

* **Nothing tracked → scan.** The window steps through the full frame plus a
  3x3 grid of overlapping tiles, one position per frame. Overlap is 50 %, so a
  hand narrower than half a tile is wholly inside at least one of them wherever
  it is. Worst case is ten frames, a third of a second, to acquire. Scanning
  rather than a fixed central box because the camera gets re-aimed and an
  exhibit must not depend on where in the frame somebody stands.
* **The full frame is one of the scan positions**, and it is the one that
  matters for a visitor standing close: their hand can be wider than a tile and
  would be cut by every one of them. Cropping without this would fix the far
  case by breaking the near case.
* **Something tracked → lock on.** The window becomes the padded union of the
  hands from the last result, so the following frames see them large. The lock
  is also what keeps the GPU backend's own ROI tracking coherent: a window that
  jumped every frame would break the track it is trying to keep.
* **Hands MOVE, so a lost lock widens before it gives up.** The window that
  held a hand last frame is the wrong window the moment that hand travels, and
  results arrive one or two frames late, so the gap is real. Each consecutive
  miss multiplies the window by `grow` around the last known centre — the
  search area chases outward from where the hand was until it either finds it
  again or reaches the whole frame, at which point scanning resumes. A fixed
  window plus a timeout would drop the visitor mid-gesture every time they
  moved quickly, which is the normal way somebody uses this exhibit.

Landmarks come back normalized to the WINDOW, so they are remapped to the full
frame before anything downstream sees them. Everything after this layer —
gestures, the UI state machine, the state payload — works in full-frame
coordinates exactly as before.

The remap uses the window that produced THAT result, not the current one:
detection is async, results arrive one or two frames late, and during a scan
the window has moved on by then. The windows are kept in a small table keyed by
the timestamp the frame was submitted with.

`HALL_HAND_VIEW=0` turns the whole thing off and restores full-frame inference.
"""

import cv2

# How many submitted windows to remember. Results arrive a frame or two late;
# anything older than that is gone and its result would be too stale to use.
_HISTORY = 16


class _Landmark:
    """A remapped landmark.

    A plain object rather than the backend's own landmark type: the two
    backends build different classes and neither promises to be mutable, while
    everything downstream only ever reads these four attributes.
    """

    __slots__ = ("x", "y", "z", "visibility", "presence")

    def __init__(self, x, y, z, visibility, presence):
        self.x = x
        self.y = y
        self.z = z
        self.visibility = visibility
        self.presence = presence


class _Result:
    """A hand result in full-frame coordinates.

    Mirrors the attribute surface both backends publish, which is the contract
    the rest of the app is written against.
    """

    __slots__ = ("hand_landmarks", "hand_world_landmarks", "handedness")

    def __init__(self, hand_landmarks, hand_world_landmarks, handedness):
        self.hand_landmarks = hand_landmarks
        self.hand_world_landmarks = hand_world_landmarks
        self.handedness = handedness


class HandViewport:
    """Chooses the window, cuts it, and puts the landmarks back where they go.

    ``scale`` is the tile size as a fraction of the frame. ``pad`` is how much
    bigger than the tracked hands the locked window is — it has to leave room
    for a hand that moves between one result and the next, which at the
    detector's rate is a lot of pixels.
    """

    def __init__(self, scale=0.5, pad=2.5, min_scale=0.35, lost_frames=5,
                 grow=1.7):
        self.scale = float(scale)
        self.pad = float(pad)
        self.min_scale = float(min_scale)
        self.lost_frames = int(lost_frames)
        self.grow = float(grow)
        self._scan = 0
        self._lock = None          # (x0, y0, w, h) in pixels, or None
        self._missed = 0
        self._boxes = {}           # timestamp_ms -> box used for that frame
        self._order = []
        # The last window actually used, in normalized frame coordinates, for
        # the debug HUD: this layer is invisible otherwise and a wrong window
        # looks exactly like a model that stopped working.
        self.last_view = None

    # -- choosing the window -------------------------------------------------

    def _positions(self, w, h):
        """Scan positions: the whole frame first, then overlapping tiles.

        The full frame leads because a close visitor's hand is the case a tile
        would cut in half, and that visitor is the one actually using the
        exhibit.
        """
        boxes = [(0, 0, w, h)]
        tw, th = int(w * self.scale), int(h * self.scale)
        for iy in range(3):
            for ix in range(3):
                x0 = int(ix * (w - tw) / 2.0)
                y0 = int(iy * (h - th) / 2.0)
                boxes.append((x0, y0, tw, th))
        return boxes

    def _locked_box(self, w, h):
        """Grow the tracked-hands box to the frame's aspect and clamp it in."""
        x0, y0, bw, bh = self._lock
        cx, cy = x0 + bw / 2.0, y0 + bh / 2.0
        # Each consecutive miss widens the search around where the hand was
        # last seen. A hand crossing the frame outruns a tight window in a
        # couple of results, and re-acquiring it by scanning the whole frame
        # from scratch is both slower and, at the far distances this layer
        # exists for, likely to fail on the full-frame position.
        reach = self.pad * (self.grow ** self._missed)
        bw *= reach
        bh *= reach
        # Never smaller than min_scale: a window tight around the hands would
        # lose them the moment they move, and the detector needs context around
        # a hand to place the wrist and the knuckles.
        bw = max(bw, w * self.min_scale)
        bh = max(bh, h * self.min_scale)
        # Match the frame's aspect ratio so the model sees undistorted geometry
        # and the remap is a single uniform scale per axis.
        if bw / bh > w / float(h):
            bh = bw * h / float(w)
        else:
            bw = bh * w / float(h)
        bw, bh = min(bw, w), min(bh, h)
        x0 = min(max(cx - bw / 2.0, 0), w - bw)
        y0 = min(max(cy - bh / 2.0, 0), h - bh)
        return int(x0), int(y0), int(bw), int(bh)

    def choose(self, w, h, timestamp_ms):
        """Pick this frame's window and record it against ``timestamp_ms``.

        Split out from :meth:`view` so the geometry — scanning, locking,
        widening, clamping — can be checked as arithmetic, with no image and
        therefore no invented camera scene anywhere near it.
        """
        if self._lock is not None:
            box = self._locked_box(w, h)
        else:
            positions = self._positions(w, h)
            box = positions[self._scan % len(positions)]
            self._scan += 1
        self._remember(timestamp_ms, box, w, h)
        x0, y0, bw, bh = box
        self.last_view = (x0 / float(w), y0 / float(h),
                          bw / float(w), bh / float(h))
        return box

    def view(self, frame, timestamp_ms):
        """Return the image to hand the detector for this frame."""
        h, w = frame.shape[:2]
        x0, y0, bw, bh = self.choose(w, h, timestamp_ms)
        if (x0, y0, bw, bh) == (0, 0, w, h):
            return frame
        crop = frame[y0:y0 + bh, x0:x0 + bw]
        # Always the same size out, whatever the window was: a detector fed a
        # frame size that changes every frame is a risk neither backend
        # promises to absorb, and resizing to the full frame keeps every pixel
        # the window contains.
        return cv2.resize(crop, (w, h), interpolation=cv2.INTER_LINEAR)

    def _remember(self, timestamp_ms, box, w, h):
        self._boxes[timestamp_ms] = (box, w, h)
        self._order.append(timestamp_ms)
        while len(self._order) > _HISTORY:
            self._boxes.pop(self._order.pop(0), None)

    # -- putting the answer back ---------------------------------------------

    def remap(self, result, timestamp_ms):
        """Rewrite a result's landmarks into full-frame coordinates.

        Also advances the lock, since this is where it is known whether the
        window that was tried found anything.
        """
        if result is None:
            return None
        entry = self._boxes.get(timestamp_ms)
        hands = getattr(result, "hand_landmarks", None) or []
        if entry is None:
            # The window for this result has aged out of the table. Its
            # coordinates cannot be trusted against any other window, so the
            # honest answer is no hands rather than hands in the wrong place.
            return None if hands else result
        (x0, y0, bw, bh), w, h = entry

        self._track(hands, x0, y0, bw, bh, w, h)
        if not hands or (x0, y0, bw, bh) == (0, 0, w, h):
            return result

        sx, sy = bw / float(w), bh / float(h)
        ox, oy = x0 / float(w), y0 / float(h)
        remapped = [[_Landmark(ox + lm.x * sx, oy + lm.y * sy,
                               getattr(lm, "z", 0.0) * sx,
                               getattr(lm, "visibility", None),
                               getattr(lm, "presence", None))
                     for lm in hand] for hand in hands]
        # World landmarks are metres about the wrist and handedness is a label:
        # neither depends on where in the frame the window was, so both pass
        # through untouched.
        return _Result(remapped,
                       getattr(result, "hand_world_landmarks", None),
                       getattr(result, "handedness", None))

    def _track(self, hands, x0, y0, bw, bh, w, h):
        """Lock onto what was found, or count towards giving up."""
        if not hands:
            self._missed += 1
            if self._missed >= self.lost_frames:
                self._lock = None
            return
        self._missed = 0
        xs = [lm.x for hand in hands for lm in hand]
        ys = [lm.y for hand in hands for lm in hand]
        # Landmark coordinates are relative to the window they were found in,
        # so they have to be lifted back to the frame before they can describe
        # the next window.
        px0 = x0 + min(xs) * bw
        px1 = x0 + max(xs) * bw
        py0 = y0 + min(ys) * bh
        py1 = y0 + max(ys) * bh
        self._lock = (px0, py0, max(px1 - px0, 1.0), max(py1 - py0, 1.0))

    def to_state(self):
        """Debug-block payload (HALL_DEBUG=1)."""
        return {
            "on": True,
            "mode": "lock" if self._lock is not None else "scan",
            "view": [round(v, 3) for v in self.last_view]
            if self.last_view else None,
        }
