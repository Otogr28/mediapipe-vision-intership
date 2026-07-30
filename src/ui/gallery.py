"""The gallery: browsing the exhibit's photographs by hand.

The second entry on the menu, next to Experiments. It reads the same
folder as the idle slideshow (``config.ATTRACT_GALLERY_DIR`` — see
``ui/attract.py``), so there is one place to put photographs and two ways to
see them: unattended as a slideshow, on demand as something a visitor flips
through themselves.

**The interaction is one gesture, and it is the one they already know.** Close
your hand anywhere, pull sideways, let go. The strip follows the hand while
held and settles on the nearest photograph on release, with a flick carrying
it one further. Nothing new to learn: the exhibit has taught "close your hand
and drag" the whole app runs on, applied to a strip.
Prev/Next buttons sit under the card for whoever does not discover the drag —
they cannot fight the drag, because `UIManager` reserves any hand over a live
button before the scene is updated.

Two decisions worth keeping:

**Cards, not full-bleed.** The neighbours peeking in at either edge are what
say "there are more of these and they move sideways" without a word of
instruction. Leaving the camera visible around the card matters too: it is
the only thing telling the visitor the screen is watching their hand.

**Drag gain, not 1:1.** ``GALLERY_DRAG_FRAC`` makes a quarter of the frame's
width worth a whole photograph. A 1:1 strip would need a full-width sweep per
photograph, and `manager.EDGE_MARGIN_FRAC` documents exactly why that fails —
the landmark model degrades near the border, so the gesture would die half
way across. This is the same problem the Spacetime camera solved with
position/rate blending, in the cheap form that a bounded, one-axis control
allows.

Two renderers, like every scene: ``draw()`` is the numpy/cv2 path for
``window``/``stream`` mode, ``to_state()`` feeds the browser. Python owns the
photo list, the position and the card geometry; the browser only paints.
"""

import math
import time

import cv2
import numpy as np

from config import (GALLERY_CARD_ASPECT, GALLERY_CARD_H_FRAC,
                    GALLERY_CARD_TOP_FRAC, GALLERY_DRAG_FRAC, GALLERY_FLICK_V,
                    GALLERY_GAP_FRAC, GALLERY_SNAP_RATE, GALLERY_WINDOW)
from detection.gestures import hand_id, pinch_state
from ui.attract import build_slides

FONT = cv2.FONT_HERSHEY_SIMPLEX

# Shortest frame interval that may contribute a flick-velocity sample (s).
# Roughly a 200 fps frame — far faster than the render loop ever runs, so in
# practice every real frame counts, while a zero-length one is discarded
# instead of dividing a pixel of cursor noise by it.
_MIN_VEL_DT = 0.005


def _cover(img, width, height):
    """Scale-and-centre-crop ``img`` to exactly ``width`` x ``height``."""
    ih, iw = img.shape[:2]
    scale = max(width / iw, height / ih)
    resized = cv2.resize(img, (max(int(round(iw * scale)), width),
                               max(int(round(ih * scale)), height)),
                         interpolation=cv2.INTER_AREA)
    y0 = (resized.shape[0] - height) // 2
    x0 = (resized.shape[1] - width) // 2
    return resized[y0:y0 + height, x0:x0 + width]


class Gallery:
    """A horizontal strip of photographs, dragged by hand."""

    def __init__(self, frame_w, frame_h, slides=None):
        self.w = frame_w
        self.h = frame_h
        self.slides = build_slides() if slides is None else list(slides)

        # `index` is the photograph the strip is settled on (an int);
        # `position` is where the strip actually is (a float), which differs
        # from it while dragging and while easing back after a release.
        self.index = 0
        self.position = 0.0

        # Drag state. `grabbed` is read by UIManager._detect_interaction to
        # retire the onboarding hint, the same as every other scene.
        self.grabbed = False
        self._drag_hand = None
        self._drag_x0 = 0.0
        self._drag_pos0 = 0.0
        # Position history for the flick, as (t, position). Two samples is
        # all a release needs and it cannot grow.
        self._vel = 0.0
        self._last_t = None
        self._last_pos = 0.0

        # Card geometry, computed once here so both renderers and the payload
        # agree on a single rect (mirrored in web/src/hud/Gallery.tsx).
        self.card_h = int(round(frame_h * GALLERY_CARD_H_FRAC))
        self.card_w = int(round(self.card_h * GALLERY_CARD_ASPECT))
        # A 16:9 card at 60 % height is wider than the frame on a 4:3 camera;
        # clamp so the neighbours still peek in rather than being pushed off.
        max_w = int(round(frame_w * 0.62))
        if self.card_w > max_w:
            self.card_w = max_w
            self.card_h = int(round(self.card_w / GALLERY_CARD_ASPECT))
        self.gap = int(round(frame_w * GALLERY_GAP_FRAC))
        self.card_x = (frame_w - self.card_w) // 2
        # High, not centred. The column below the card has to hold the
        # caption, the counter AND the Prev/Next row, and EDGE_MARGIN_FRAC
        # already claims a tenth of the frame at the bottom for those
        # buttons — centring the card put the counter underneath them.
        self.card_y = int(round(frame_h * GALLERY_CARD_TOP_FRAC))

        # Cover-cropped card images by slide index, bounded to the strip the
        # renderer can actually show (the Orin shares 8 GB with a browser).
        self._cache = {}

    # --- geometry -------------------------------------------------------

    @property
    def _stride(self):
        """Frame pixels between one card's left edge and the next."""
        return self.card_w + self.gap

    def _drag_px(self):
        """Hand travel worth one photograph, in pixels."""
        return max(self.w * GALLERY_DRAG_FRAC, 1.0)

    def card_rect(self, i):
        """Where card ``i`` sits this frame, given the strip's position."""
        x = self.card_x + int(round((i - self.position) * self._stride))
        return x, self.card_y, self.card_w, self.card_h

    # --- navigation -----------------------------------------------------

    def _clamp(self, value):
        return max(0.0, min(float(value), max(len(self.slides) - 1, 0)))

    def step(self, delta):
        """Move by whole photographs — what the Prev/Next buttons call."""
        self.index = int(self._clamp(self.index + delta))

    def update(self, hand_result, pose_landmarks):
        now = time.monotonic()
        dt = 0.0 if self._last_t is None else max(now - self._last_t, 0.0)
        self._last_t = now

        if not self.slides:
            return

        if self.grabbed:
            # Owner latch, like every other grab in the app: only the hand
            # that started the drag may continue it, and reading its machine
            # directly (rather than this frame's hand list) lets the drag
            # ride out a short tracking dropout.
            _pinching, held, (mx, _my) = pinch_state(self._drag_hand)
            if held:
                # Drag RIGHT moves the strip right, which brings the PREVIOUS
                # photograph into view — the strip is the thing being moved,
                # not a scrollbar.
                moved = (mx - self._drag_x0) / self._drag_px()
                self.position = self._clamp(self._drag_pos0 - moved)
            else:
                self._release()
        elif hand_result is not None:
            for i in range(len(hand_result.hand_landmarks)):
                hid = hand_id(hand_result, i)
                pinching, _held, (mx, _my) = pinch_state(hid)
                # Only the fresh close event starts a drag, so a hand that
                # was already closed when it entered the gallery does not
                # yank the strip. `pinch_state` also withholds that event
                # from a hand parked over Prev/Next.
                if pinching:
                    self.grabbed = True
                    self._drag_hand = hid
                    self._drag_x0 = mx
                    self._drag_pos0 = self.position
                    self._vel = 0.0
                    break

        if self.grabbed:
            if dt >= _MIN_VEL_DT:
                # Photographs per second, smoothed a little so one jittery
                # frame at the moment of release cannot fling the strip.
                # Samples from an implausibly short frame are dropped rather
                # than divided by: a dt of a millisecond turns a pixel of
                # cursor noise into a velocity of tens of photographs per
                # second, and every release would read as a flick.
                v = (self.position - self._last_pos) / dt
                self._vel = 0.7 * self._vel + 0.3 * v
                self._last_pos = self.position
        else:
            # Ease back to the settled photograph. Exponential rather than
            # linear so it decelerates into place instead of stopping dead.
            k = min(dt * GALLERY_SNAP_RATE, 1.0)
            self.position += (self.index - self.position) * k
            self._vel = 0.0
            self._last_pos = self.position

    def _release(self):
        """Decide which photograph the strip settles on."""
        target = round(self.position)
        if abs(self._vel) >= GALLERY_FLICK_V:
            # A flick goes to the next card in the direction of travel from
            # wherever the drag got to, rather than to the nearest one. That
            # is what makes a short fast swipe work at all: without it, a
            # flick that only covered a third of a card snaps back to the
            # one it started on and reads as the gallery ignoring you.
            target = (math.floor(self.position) + 1 if self._vel > 0
                      else math.ceil(self.position) - 1)
        self.index = int(self._clamp(target))
        self.grabbed = False
        self._drag_hand = None
        self._vel = 0.0

    # --- serialization --------------------------------------------------

    def _window(self):
        """The slide indices the renderer can actually show right now."""
        centre = int(round(self.position))
        lo = max(centre - GALLERY_WINDOW, 0)
        hi = min(centre + GALLERY_WINDOW, len(self.slides) - 1)
        return range(lo, hi + 1)

    def to_state(self):
        """Payload carries a WINDOW of the strip, never the folder.

        The gallery folder holds however many photographs somebody dropped in
        it and this ships at ``STATE_FPS``; the browser only ever paints the
        five cards around the current one.
        """
        return {
            "type": "gallery",
            "index": self.index,
            "position": round(self.position, 3),
            "count": len(self.slides),
            "grabbed": self.grabbed,
            # Card rect at position 0 offset, plus the stride — the browser
            # places card i at x = card[0] + (i - position) * stride.
            "card": [self.card_x, self.card_y, self.card_w, self.card_h],
            "stride": self._stride,
            "slides": [
                {"index": i,
                 "src": self.slides[i]["src"],
                 "title": self.slides[i]["title"],
                 "caption": self.slides[i]["caption"]}
                for i in self._window()
            ],
        }

    # --- cv2 renderer ---------------------------------------------------

    def _image(self, i):
        """Cover-cropped card image ``i``, or None if it cannot be read."""
        if i in self._cache:
            return self._cache[i]
        img = cv2.imread(self.slides[i]["path"])
        card = None if img is None else _cover(img, self.card_w, self.card_h)
        if len(self._cache) > 2 * GALLERY_WINDOW + 2:
            self._cache.clear()
        self._cache[i] = card
        return card

    def draw(self, frame):
        h, w = frame.shape[:2]

        # Dim the camera so the cards read as the subject, without hiding the
        # visitor entirely — they still need to see themselves gesturing.
        frame[:] = (frame * 0.45).astype(np.uint8)

        if not self.slides:
            text = "No photographs in the gallery folder"
            (tw, _th), _ = cv2.getTextSize(text, FONT, 0.9, 2)
            cv2.putText(frame, text, ((w - tw) // 2, h // 2), FONT, 0.9,
                        (200, 200, 200), 2, cv2.LINE_AA)
            return

        for i in self._window():
            x, y, cw, ch = self.card_rect(i)
            # Clip to the frame: a card halfway off the edge still draws its
            # visible part, which is exactly the "there is more over there"
            # cue the strip depends on.
            sx0, sx1 = max(x, 0), min(x + cw, w)
            sy0, sy1 = max(y, 0), min(y + ch, h)
            if sx0 >= sx1 or sy0 >= sy1:
                continue
            card = self._image(i)
            if card is None:
                frame[sy0:sy1, sx0:sx1] = (40, 40, 46)
            else:
                frame[sy0:sy1, sx0:sx1] = card[sy0 - y:sy1 - y,
                                               sx0 - x:sx1 - x]
            # A border so two adjacent photographs of similar colour do not
            # merge into one picture.
            colour = (255, 255, 255) if i == self.index else (90, 90, 95)
            cv2.rectangle(frame, (x, y), (x + cw, y + ch), colour, 2)

        # Caption of the settled photograph, then the position counter. Both
        # sit between the card and the Prev/Next row; the offsets are
        # mirrored in web/src/hud/Gallery.tsx.
        slide = self.slides[self.index]
        below = self.card_y + self.card_h
        if slide["title"]:
            (tw, _th), _ = cv2.getTextSize(slide["title"], FONT, 0.85, 2)
            cv2.putText(frame, slide["title"], ((w - tw) // 2, below + 34),
                        FONT, 0.85, (245, 245, 245), 2, cv2.LINE_AA)

        text = f"{self.index + 1} / {len(self.slides)}"
        (tw, _th), _ = cv2.getTextSize(text, FONT, 0.6, 2)
        cv2.putText(frame, text, ((w - tw) // 2,
                                  below + (66 if slide["title"] else 34)),
                    FONT, 0.6, (185, 185, 190), 2, cv2.LINE_AA)

        hint = "Close your hand and drag to browse"
        (tw, _th), _ = cv2.getTextSize(hint, FONT, 0.55, 1)
        cv2.putText(frame, hint, ((w - tw) // 2, self.card_y - 22), FONT,
                    0.55, (120, 200, 255), 1, cv2.LINE_AA)
