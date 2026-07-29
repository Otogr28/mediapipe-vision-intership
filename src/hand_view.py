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

**One window per HAND, not one per frame.** The first version tracked a single
window around the union of every hand found, and it could not do two hands at
once: arms apart at exhibit distance put the two hands ~470 px apart in a
1280-wide frame, so their union padded out past the whole frame and the size
advantage vanished exactly when it was needed. Since `Spacetime`'s camera needs
two simultaneous pinches and the 6-7 counter uses both arms, that is a real
gap, so each hand now gets its OWN window and the windows take turns:

* **Nothing tracked → scan.** One position per frame over the full frame plus a
  3x3 grid of tiles overlapping by 50 %, so a hand narrower than half a tile is
  wholly inside at least one of them wherever it is. The full frame leads
  because a close visitor's hand can be wider than a tile and every tile would
  cut it. Worst case ten frames, a third of a second, to acquire.
* **Hands tracked → round-robin over their windows**, one per frame. With two
  hands each is refreshed every other frame; the published result carries the
  freshest landmarks for BOTH, so everything downstream still sees two hands in
  the same frame and two-hand gestures keep working.
* **Room for another hand → seek.** While fewer than `max_hands` are tracked,
  every `seek_every`-th turn goes to a scan position instead of a tracked
  window, so a second hand entering the frame is found without dropping the
  first. With one hand that leaves it refreshed on two turns out of three.
* **Hands MOVE, so a lost window widens before it is given up.** Each
  consecutive miss on a slot multiplies its window by `grow` around where that
  hand was last seen; the search chases outward until it finds the hand again
  or reaches the whole frame. Only after `lost_frames` misses is the slot
  dropped. A fixed window plus a timeout would lose the visitor mid-gesture
  every time they moved quickly, which is how people actually use this.

Landmarks come back normalized to the window they were found in and are
remapped to the full frame before anything downstream sees them, so gestures,
the UI state machine and the state payload all keep working in full-frame
coordinates exactly as before.

The remap uses the window that produced THAT result, not the current one:
detection is async, results arrive one or two frames late, and by then the
rotation has moved to the other hand. Windows are kept in a small table keyed
by the timestamp the frame was submitted with, and each result is ingested
exactly once however many render frames it stays the newest for.

Slots are matched to detections by handedness first and position second, so a
hand keeps its identity across frames — `gestures.hand_id()` keys the pinch
state machines on handedness, and a slot that swapped identity would hand a
half-closed pinch to the other hand.

`HALL_HAND_VIEW=0` turns the whole thing off and restores full-frame inference.
"""

import cv2

# How many submitted windows to remember. Results arrive a frame or two late;
# anything older than that is gone and its result would be too stale to use.
_HISTORY = 24

# Farthest a detection can be from a slot's last position, in fractions of the
# frame, and still be taken for the same hand. Generous, because the whole
# point is that hands move fast; identity is confirmed by handedness whenever
# the backend reports it.
_MATCH_DIST = 0.35


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


class _Slot:
    """One tracked hand: where it was, what it looked like, how stale it is."""

    __slots__ = ("cx", "cy", "w", "h", "landmarks", "world", "handed",
                 "missed", "seen_ms")

    def __init__(self, cx, cy, w, h, landmarks, world, handed, seen_ms):
        self.cx = cx
        self.cy = cy
        self.w = w
        self.h = h
        self.landmarks = landmarks
        self.world = world
        self.handed = handed
        self.missed = 0
        self.seen_ms = seen_ms

    def label(self):
        try:
            return self.handed[0].category_name
        except Exception:
            return None


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


class HandViewport:
    """Chooses the windows, cuts them, and puts the landmarks back where they go.

    ``scale`` is the tile size as a fraction of the frame while scanning.
    ``pad`` is how much bigger than a tracked hand its window is — it has to
    leave room for a hand that moves between one result and the next, which at
    the detector's rate is a lot of pixels.
    """

    def __init__(self, scale=0.5, pad=2.5, min_scale=0.35, lost_frames=5,
                 grow=1.7, max_hands=2, seek_every=3, hold_ms=400):
        self.scale = float(scale)
        self.pad = float(pad)
        self.min_scale = float(min_scale)
        self.lost_frames = int(lost_frames)
        self.grow = float(grow)
        self.max_hands = int(max_hands)
        self.seek_every = max(int(seek_every), 2)
        self.hold_ms = float(hold_ms)
        self._slots = []
        self._scan = 0        # which scan position comes next
        self._rr = 0          # which tracked slot's turn it is
        self._tick = 0        # turns taken, for the seek cadence
        self._boxes = {}      # timestamp_ms -> (box, frame_w, frame_h, target)
        self._order = []
        self._last_ingest = None
        # The last window actually used, normalized, and what it was for. This
        # layer is invisible when it works, and a wrong window looks exactly
        # like a model that stopped finding hands.
        self.last_view = None
        self.last_target = "scan"

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
                boxes.append((int(ix * (w - tw) / 2.0),
                              int(iy * (h - th) / 2.0), tw, th))
        return boxes

    def _slot_box(self, slot, w, h):
        """That hand's window: padded, widened by its misses, clamped inside."""
        # Each consecutive miss widens the search around where the hand was
        # last seen. A hand crossing the frame outruns a tight window in a
        # couple of results, and re-acquiring it by scanning from scratch is
        # both slower and, at the distances this layer exists for, likely to
        # fail on the full-frame position.
        reach = self.pad * (self.grow ** slot.missed)
        bw = max(slot.w * reach, w * self.min_scale)
        bh = max(slot.h * reach, h * self.min_scale)
        # Match the frame's aspect ratio so the model sees undistorted geometry
        # and the remap is a single uniform scale per axis.
        if bw / bh > w / float(h):
            bh = bw * h / float(w)
        else:
            bw = bh * w / float(h)
        bw, bh = min(bw, w), min(bh, h)
        x0 = _clamp(slot.cx - bw / 2.0, 0, w - bw)
        y0 = _clamp(slot.cy - bh / 2.0, 0, h - bh)
        return int(x0), int(y0), int(bw), int(bh)

    def _next_target(self):
        """Whose turn it is: a tracked slot, or a scan position.

        Scanning while a hand is already tracked is what lets a SECOND hand be
        found without dropping the first, and it is rationed rather than
        alternated so the tracked hand keeps most of the frames.
        """
        turn = self._tick
        self._tick += 1
        if not self._slots:
            return None
        if len(self._slots) < self.max_hands and turn % self.seek_every == 0:
            return None
        i = self._rr % len(self._slots)
        self._rr += 1
        return i

    def choose(self, w, h, timestamp_ms):
        """Pick this frame's window and record it against ``timestamp_ms``.

        Split out from :meth:`view` so the geometry — scanning, the rotation,
        locking, widening, clamping — can be checked as arithmetic, with no
        image and therefore no invented camera scene anywhere near it.
        """
        target = self._next_target()
        if target is None:
            box = self._positions(w, h)[self._scan % (1 + 9)]
            self._scan += 1
            self.last_target = "scan"
        else:
            box = self._slot_box(self._slots[target], w, h)
            self.last_target = "hand%d" % target
        self._remember(timestamp_ms, box, w, h, target)
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

    def _remember(self, timestamp_ms, box, w, h, target):
        self._boxes[timestamp_ms] = (box, w, h, target)
        self._order.append(timestamp_ms)
        while len(self._order) > _HISTORY:
            self._boxes.pop(self._order.pop(0), None)

    # -- putting the answer back ---------------------------------------------

    def remap(self, result, timestamp_ms):
        """Ingest a result and return every tracked hand, in frame coordinates.

        Returns the MERGED view rather than just this result: with one window
        per hand, any single result speaks for one of them, and the app has to
        keep seeing both.
        """
        entry = self._boxes.get(timestamp_ms) if result is not None else None
        # The same packet stays newest for as long as the loop outruns the
        # detector. Ingesting it repeatedly would count one miss many times and
        # retire a slot that is merely waiting for its turn.
        fresh = (result is not None and entry is not None
                 and timestamp_ms != self._last_ingest)
        if fresh:
            self._last_ingest = timestamp_ms
            (x0, y0, bw, bh), w, h, target = entry
            self._ingest(result, x0, y0, bw, bh, w, h, target, timestamp_ms)
        self._retire(timestamp_ms)
        return self._merged()

    def _ingest(self, result, x0, y0, bw, bh, w, h, target, now_ms):
        hands = getattr(result, "hand_landmarks", None) or []
        world = getattr(result, "hand_world_landmarks", None) or []
        handed = getattr(result, "handedness", None) or []
        if not hands:
            # Only the slot that was actually looked at can be said to have
            # been missed. The other one was not being looked for.
            if target is not None and target < len(self._slots):
                self._slots[target].missed += 1
            return

        sx, sy = bw / float(w), bh / float(h)
        ox, oy = x0 / float(w), y0 / float(h)
        seen = set()
        for i, hand in enumerate(hands):
            if not hand:
                continue          # a backend that reported an empty hand
            lms = [_Landmark(ox + lm.x * sx, oy + lm.y * sy,
                             getattr(lm, "z", 0.0) * sx,
                             getattr(lm, "visibility", None),
                             getattr(lm, "presence", None))
                   for lm in hand]
            xs = [lm.x for lm in lms]
            ys = [lm.y for lm in lms]
            cx = (min(xs) + max(xs)) / 2.0 * w
            cy = (min(ys) + max(ys)) / 2.0 * h
            bw_px = max((max(xs) - min(xs)) * w, 1.0)
            bh_px = max((max(ys) - min(ys)) * h, 1.0)
            hd = handed[i] if i < len(handed) else None
            wl = world[i] if i < len(world) else None
            j = self._match(cx, cy, w, h, hd, seen)
            if j is None:
                if len(self._slots) >= self.max_hands:
                    continue
                self._slots.append(_Slot(cx, cy, bw_px, bh_px, lms, wl, hd,
                                         now_ms))
                seen.add(len(self._slots) - 1)
                continue
            slot = self._slots[j]
            slot.cx, slot.cy, slot.w, slot.h = cx, cy, bw_px, bh_px
            slot.landmarks, slot.world, slot.seen_ms = lms, wl, now_ms
            # Keep the label a slot already had if this result did not report
            # one: identity downstream is keyed on it.
            if hd:
                slot.handed = hd
            slot.missed = 0
            seen.add(j)

        # A window that was looked at and came back without ITS hand still
        # counts as a miss, even though it found somebody else's.
        if target is not None and target < len(self._slots) \
                and target not in seen:
            self._slots[target].missed += 1

    def _match(self, cx, cy, w, h, handed, taken):
        """Which slot this detection belongs to, or None for a new hand.

        Handedness first, because it is the identity `gestures.hand_id()` keys
        on; position second, for the backends and frames where it is missing.
        """
        label = None
        if handed:
            try:
                label = handed[0].category_name
            except Exception:
                label = None
        if label is not None:
            for j, slot in enumerate(self._slots):
                if j not in taken and slot.label() == label:
                    return j
        best, best_d = None, _MATCH_DIST
        for j, slot in enumerate(self._slots):
            if j in taken:
                continue
            # Distance in frame fractions, so it means the same at any capture
            # resolution.
            d = (((slot.cx - cx) / float(w)) ** 2
                 + ((slot.cy - cy) / float(h)) ** 2) ** 0.5
            if d < best_d:
                best, best_d = j, d
        return best

    def _retire(self, now_ms):
        """Drop slots that ran out of misses or went stale."""
        keep = []
        for slot in self._slots:
            if slot.missed >= self.lost_frames:
                continue
            if now_ms is not None and slot.seen_ms is not None \
                    and now_ms - slot.seen_ms > self.hold_ms:
                continue
            keep.append(slot)
        if len(keep) != len(self._slots):
            self._slots = keep
            self._rr = 0
        return self._slots

    def _merged(self):
        """Every tracked hand's freshest landmarks, as one result.

        Slot order is creation order and never shuffles, so the index fallback
        in `gestures.hand_id()` is as stable as the handedness path.
        """
        if not self._slots:
            return None
        return _Result([s.landmarks for s in self._slots],
                       [s.world for s in self._slots],
                       [s.handed for s in self._slots])

    def to_state(self):
        """Debug-block payload (HALL_DEBUG=1)."""
        return {
            "on": True,
            "mode": self.last_target,
            "tracked": len(self._slots),
            "view": [round(v, 3) for v in self.last_view]
            if self.last_view else None,
        }
