"""Attract mode: what the exhibit shows when nobody is standing at it.

An exhibit spends most of its day alone. Without this the app showed a live
feed of an empty corridor with a menu floating over it, still sitting in
whatever scene the last visitor walked away from. Attract mode gives the
display the two states people expect from a screen in a public building:

* :class:`AttractScreen` — the idle slideshow. One photograph per experiment,
  cross-fading, with a line saying what the screen actually is. The camera
  feed is covered: an empty room is not interesting to look at, and a public
  display that is not showing passers-by their own image unprompted is the
  polite default.
* :class:`Greeting` — the few seconds after somebody walks up. A "Hi" and one
  animated demonstration of the gesture that drives everything, so a visitor
  learns the control before they need it. A visitor who makes the gesture
  during it skips straight through: trying the control is a better way out
  than waiting for a bar to fill.

Both follow the project's two-renderer contract — ``draw()`` is the
numpy/cv2 path for ``window``/``stream`` mode, ``to_state()`` feeds the
browser in ``web`` mode, and the two must show the same thing. Neither owns
the presence decision (that is ``ui/presence.py``) or the phase machine
(that is ``UIManager``); they are given a clock and asked to render.
"""

import glob
import os
import time

import cv2
import numpy as np

from config import (ATTRACT_DIR, ATTRACT_FADE_S, ATTRACT_PROMPT,
                    ATTRACT_SLIDE_S, ATTRACT_SLIDE_TEXT, ATTRACT_TITLE,
                    GREETING_S, GREETING_SUBTITLE, GREETING_TITLE,
                    HINT_PINCH_PERIOD_S, HINT_TEXT)
from ui.hints import draw_gesture_hand, gesture_openness

FONT = cv2.FONT_HERSHEY_SIMPLEX

# The frontend fetches slide images from this route; `output.WebSink` serves
# it out of ATTRACT_DIR. Kept off `web/dist` on purpose — the photographs are
# already committed once for the exhibit website, and `web/dist` travels to
# the Jetson in every pull.
SLIDE_URL_PREFIX = "/attract/"

_IMAGE_GLOBS = ("*.jpg", "*.jpeg", "*.png", "*.webp")


def build_slides(directory=ATTRACT_DIR):
    """The slideshow, one entry per image found in ``directory``.

    Sorted by filename so the order is the same on every machine and after
    every restart. Titles and captions come from ``ATTRACT_SLIDE_TEXT``,
    keyed by the file stem — which is also the ``session.experiment`` key, so
    a slide and the QR page for the same experiment can never drift apart. An
    unknown stem still shows, captioned by its own filename, because a
    missing caption is not a reason to hide a picture.
    """
    paths = []
    for pattern in _IMAGE_GLOBS:
        paths.extend(glob.glob(os.path.join(directory, pattern)))
    slides = []
    for path in sorted(paths):
        name = os.path.basename(path)
        key = os.path.splitext(name)[0]
        title, caption = ATTRACT_SLIDE_TEXT.get(
            key, (key.replace("_", " ").title(), ""))
        slides.append({"key": key, "path": path,
                       "src": SLIDE_URL_PREFIX + name,
                       "title": title, "caption": caption})
    return slides


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


def _put(frame, text, x, y, scale, color, thick):
    cv2.putText(frame, text, (int(x), int(y)), FONT, scale, color, thick,
                cv2.LINE_AA)


def _put_centered(frame, text, cx, y, scale, color, thick):
    (tw, _th), _ = cv2.getTextSize(text, FONT, scale, thick)
    _put(frame, text, cx - tw / 2, y, scale, color, thick)


class AttractScreen:
    """The idle slideshow, and the clock that advances it."""

    def __init__(self, frame_w, frame_h, slides=None):
        self.frame_w = frame_w
        self.frame_h = frame_h
        self.slides = build_slides() if slides is None else slides
        self._start = time.monotonic()
        # Cover-cropped images, keyed by slide index. Bounded to the two the
        # cross-fade needs: at 1280x720 each is 2.6 MB, and the Jetson shares
        # 8 GB between the CPU, the GPU and a browser.
        self._cache = {}

    def enter(self, now=None):
        """Restart the slideshow from its first slide."""
        self._start = time.monotonic() if now is None else now

    def _position(self, now=None):
        """``(index, prev_index, fade)`` — fade 1.0 means fully on ``index``."""
        n = len(self.slides)
        if n == 0:
            return 0, 0, 1.0
        now = time.monotonic() if now is None else now
        elapsed = max(now - self._start, 0.0)
        index = int(elapsed // ATTRACT_SLIDE_S) % n
        into = elapsed % ATTRACT_SLIDE_S
        # No fade on the very first slide: there is nothing to fade FROM, and
        # fading up from a black frame reads as the display booting.
        if into >= ATTRACT_FADE_S or elapsed < ATTRACT_SLIDE_S:
            return index, index, 1.0
        return index, (index - 1) % n, into / ATTRACT_FADE_S

    def to_state(self, now=None):
        index, prev, fade = self._position(now)
        return {
            "title": ATTRACT_TITLE,
            "prompt": ATTRACT_PROMPT,
            "index": index,
            "prev": prev,
            "fade": round(fade, 3),
            "slides": [{"src": s["src"], "title": s["title"],
                        "caption": s["caption"]} for s in self.slides],
        }

    def _image(self, index):
        """Cover-cropped slide ``index``, or None if it cannot be read."""
        if index in self._cache:
            return self._cache[index]
        img = cv2.imread(self.slides[index]["path"])
        cover = None if img is None else _cover(img, self.frame_w,
                                                self.frame_h)
        if len(self._cache) >= 2:
            self._cache.clear()      # only the fading pair is ever needed
        self._cache[index] = cover
        return cover

    def draw(self, frame, now=None):
        """Paint the whole frame — this REPLACES the camera image."""
        h, w = frame.shape[:2]
        if not self.slides:
            frame[:] = (24, 18, 12)
            _put_centered(frame, ATTRACT_TITLE, w / 2, h * 0.48, 1.6,
                          (240, 240, 240), 3)
            _put_centered(frame, ATTRACT_PROMPT, w / 2, h * 0.58, 0.7,
                          (170, 170, 170), 2)
            return

        index, prev, fade = self._position(now)
        current = self._image(index)
        if current is None:
            frame[:] = (24, 18, 12)
        elif fade < 1.0 and prev != index:
            previous = self._image(prev)
            if previous is None:
                frame[:] = current
            else:
                cv2.addWeighted(current, fade, previous, 1.0 - fade, 0.0,
                                dst=frame)
        else:
            frame[:] = current

        # Caption band along the bottom: a gradient-free flat scrim keeps the
        # text legible over any photograph without a second blur pass.
        band_h = int(h * 0.22)
        band = frame[h - band_h:h]
        band[:] = (band * 0.35).astype(np.uint8)

        slide = self.slides[index]
        _put(frame, slide["title"], w * 0.06, h - band_h + h * 0.075, 1.3,
             (245, 245, 245), 3)
        if slide["caption"]:
            _put(frame, slide["caption"], w * 0.06, h - band_h + h * 0.125,
                 0.7, (205, 205, 205), 2)
        _put(frame, ATTRACT_PROMPT, w * 0.06, h - h * 0.035, 0.62,
             (120, 200, 255), 2)

        # Slide position dots, bottom-right.
        dot_r = max(int(h * 0.006), 2)
        gap = dot_r * 4
        x = w - w * 0.06 - gap * (len(self.slides) - 1)
        y = int(h - h * 0.045)
        for i in range(len(self.slides)):
            colour = (245, 245, 245) if i == index else (110, 110, 110)
            cv2.circle(frame, (int(x + gap * i), y), dot_r, colour, -1,
                       cv2.LINE_AA)


class Greeting:
    """The "Hi" + gesture demo shown to somebody who just walked up."""

    def __init__(self, frame_w, frame_h):
        self.frame_w = frame_w
        self.frame_h = frame_h
        self._start = time.monotonic()

    def enter(self, now=None):
        self._start = time.monotonic() if now is None else now

    def elapsed(self, now=None):
        return max((time.monotonic() if now is None else now) - self._start,
                   0.0)

    def done(self, now=None):
        return self.elapsed(now) >= GREETING_S

    def to_state(self, now=None):
        return {
            "title": GREETING_TITLE,
            "subtitle": GREETING_SUBTITLE,
            "hint": HINT_TEXT,
            "t": round(self.elapsed(now), 2),
            "duration": GREETING_S,
        }

    def draw(self, frame, now=None):
        """Dark glass over the live camera, so the visitor sees themselves
        arrive behind the instructions — the moment that tells them the
        screen is reacting to them and not playing a video."""
        h, w = frame.shape[:2]
        cx = w / 2.0
        layer = cv2.addWeighted(frame, 0.28, np.zeros_like(frame), 0.0, 0.0)

        _put_centered(layer, GREETING_TITLE, cx, h * 0.20, 2.4,
                      (255, 255, 255), 5)
        _put_centered(layer, GREETING_SUBTITLE, cx, h * 0.20 + 46, 0.72,
                      (205, 205, 205), 2)

        s = min(w, h) * 0.34
        draw_gesture_hand(layer, cx, h * 0.55, s,
                          gesture_openness(self._start, HINT_PINCH_PERIOD_S,
                                           now))
        _put_centered(layer, HINT_TEXT, cx, h * 0.55 + s * 0.72, 0.85,
                      (255, 255, 255), 2)

        prog = min(self.elapsed(now) / GREETING_S, 1.0)
        bar_w = int(w * 0.36)
        bx, by, bh = int(cx - bar_w / 2), int(h * 0.88), 6
        cv2.rectangle(layer, (bx, by), (bx + bar_w, by + bh), (80, 80, 80), -1)
        cv2.rectangle(layer, (bx, by), (bx + int(bar_w * prog), by + bh),
                      (0, 200, 255), -1)

        frame[:] = layer
