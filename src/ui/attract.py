"""Attract mode: what the exhibit shows when nobody is standing at it.

An exhibit spends most of its day alone. Without this the app showed a live
feed of an empty corridor with a menu floating over it, still sitting in
whatever scene the last visitor walked away from. Attract mode gives the
display the two states people expect from a screen in a public building:

* :class:`AttractScreen` — the idle slideshow, cross-fading through whatever
  is in the gallery folder (``config.ATTRACT_GALLERY_DIR``), with a line
  saying what the screen actually is. The folder is the interface: copy a
  photograph in and it joins the rotation within a minute, with no restart
  and nothing to edit. The camera feed is covered while it runs — an empty
  room is not interesting to look at, and a public display that is not
  showing passers-by their own image unprompted is the polite default.
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
from urllib.parse import quote

import cv2
import numpy as np

from config import (ATTRACT_DIR, ATTRACT_FADE_S, ATTRACT_GALLERY_DIR,
                    ATTRACT_MAX_DOTS, ATTRACT_PROMPT, ATTRACT_RESCAN_S,
                    ATTRACT_SLIDE_S, ATTRACT_SLIDE_TEXT, ATTRACT_TITLE,
                    GREETING_S, GREETING_SUBTITLE, GREETING_TITLE,
                    HINT_PINCH_PERIOD_S, HINT_TEXT)
from ui.hints import draw_gesture_hand, gesture_openness

FONT = cv2.FONT_HERSHEY_SIMPLEX

# The frontend fetches slide images from this route; `output.WebSink` serves
# it out of whatever `slides_dir()` resolved to. Kept off `web/dist` on
# purpose — `web/dist` travels to the Jetson in every pull, and the gallery
# is a folder on the device that nobody should have to rebuild to change.
SLIDE_URL_PREFIX = "/attract/"

_IMAGE_GLOBS = ("*.jpg", "*.jpeg", "*.JPG", "*.JPEG", "*.png", "*.PNG",
                "*.webp")


def _image_paths(directory):
    """Every image in ``directory``, deduplicated and sorted by filename.

    Sorted so the order is the same on every machine and after every restart.
    Deduplicated because the case-variant globs above double-count on a
    case-insensitive filesystem, and a slide appearing twice in a row reads
    as the slideshow having stalled.
    """
    if not directory or not os.path.isdir(directory):
        return []
    found = set()
    for pattern in _IMAGE_GLOBS:
        found.update(glob.glob(os.path.join(directory, pattern)))
    # Empty files are what a half-finished copy looks like; cv2 and the
    # browser both render them as nothing, so drop them rather than show a
    # black slide for 6.5 s.
    return sorted(p for p in found if os.path.getsize(p) > 0)


def slides_dir():
    """Which directory the slideshow is reading right now.

    ``ATTRACT_GALLERY_DIR`` (a plain folder outside the repo — see
    ``config.py``) whenever it holds at least one image, otherwise the
    repo's ``ATTRACT_DIR`` experiment stills. Resolved fresh on every call
    rather than latched at startup: a gallery folder that gets its first
    photograph an hour after boot should start being used, and
    ``output.WebSink`` has to serve out of the same directory the slide list
    was built from.
    """
    if _image_paths(ATTRACT_GALLERY_DIR):
        return ATTRACT_GALLERY_DIR
    return ATTRACT_DIR


def build_slides(directory=None):
    """The slideshow, one entry per image found in ``directory``.

    Titles and captions come from ``ATTRACT_SLIDE_TEXT``, keyed by the file
    stem — which is also the ``session.experiment`` key, so a slide and the
    QR page for the same experiment can never drift apart. A stem that is not
    in the table gets **no** caption at all: the gallery folder is full of
    camera filenames, and "20250919 171142" set in 60px type under a
    photograph looks like a bug, not a caption.

    Filenames are URL-quoted for ``src``. Nothing sanitises what lands in the
    gallery folder, so spaces and parentheses out of a phone are the normal
    case and have to survive the round trip to ``/attract/<name>``.
    """
    if directory is None:
        directory = slides_dir()
    slides = []
    for path in _image_paths(directory):
        name = os.path.basename(path)
        key = os.path.splitext(name)[0]
        title, caption = ATTRACT_SLIDE_TEXT.get(key, ("", ""))
        slides.append({"key": key, "path": path,
                       "src": SLIDE_URL_PREFIX + quote(name),
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
        # A caller-supplied list is frozen (that is the test/mock path); a
        # self-built one is rescanned, so the exhibit picks up photographs
        # copied into the gallery folder without a restart.
        self._fixed = slides is not None
        self.slides = list(slides) if self._fixed else build_slides()
        self._start = time.monotonic()
        self._scan_t = self._start
        # Cover-cropped images, keyed by slide index. Bounded to the two the
        # cross-fade needs: at 1280x720 each is 2.6 MB, and the Jetson shares
        # 8 GB between the CPU, the GPU and a browser.
        self._cache = {}

    def enter(self, now=None):
        """Restart the slideshow from its first slide."""
        now = time.monotonic() if now is None else now
        self._start = now
        self._rescan(now, force=True)

    def _rescan(self, now, force=False):
        """Re-read the gallery folder, at most every ``ATTRACT_RESCAN_S``.

        The cost is one directory listing per minute, and what it buys is
        that adding a photograph to a machine bolted behind a plinth is a
        file copy and nothing else — no restart, no redeploy, no rebuild.
        The list is only swapped in when it actually differs, so the image
        cache survives the common case where nothing changed.
        """
        if self._fixed:
            return
        if not force and now - self._scan_t < ATTRACT_RESCAN_S:
            return
        self._scan_t = now
        slides = build_slides()
        if [s["path"] for s in slides] != [s["path"] for s in self.slides]:
            self.slides = slides
            self._cache.clear()

    def _position(self, now=None):
        """``(index, prev_index, fade)`` — fade 1.0 means fully on ``index``."""
        now = time.monotonic() if now is None else now
        self._rescan(now)
        n = len(self.slides)
        if n == 0:
            return 0, 0, 1.0
        elapsed = max(now - self._start, 0.0)
        index = int(elapsed // ATTRACT_SLIDE_S) % n
        into = elapsed % ATTRACT_SLIDE_S
        # No fade on the very first slide: there is nothing to fade FROM, and
        # fading up from a black frame reads as the display booting.
        if into >= ATTRACT_FADE_S or elapsed < ATTRACT_SLIDE_S:
            return index, index, 1.0
        return index, (index - 1) % n, into / ATTRACT_FADE_S

    def _slide_state(self, index):
        if not self.slides:
            return None
        s = self.slides[index % len(self.slides)]
        return {"src": s["src"], "title": s["title"], "caption": s["caption"]}

    def to_state(self, now=None):
        """The payload carries only the two or three slides the browser has
        to paint, never the whole list.

        A gallery folder holds however many photographs somebody dropped in
        it, and this block ships at ``STATE_FPS`` over SSE — a list of 80
        filenames re-sent thirty times a second is pure waste, and the
        frontend mounting 80 ``<img>`` elements to hide 78 of them is worse.
        So: the one fading in, the one fading out, and the one after, which
        the browser keeps mounted at zero opacity purely so it is decoded
        before its turn comes.
        """
        index, prev, fade = self._position(now)
        return {
            "title": ATTRACT_TITLE,
            "prompt": ATTRACT_PROMPT,
            "index": index,
            "count": len(self.slides),
            "fade": round(fade, 3),
            "current": self._slide_state(index),
            "previous": (self._slide_state(prev) if prev != index else None),
            "next": (self._slide_state(index + 1)
                     if len(self.slides) > 1 else None),
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

        # A gallery photograph has no title, so the band leads with what the
        # screen IS. With a titled slide (the experiment stills) that line
        # becomes the eyebrow above it, which is also how the browser lays
        # the two out.
        slide = self.slides[index]
        if slide["title"]:
            _put(frame, ATTRACT_TITLE, w * 0.06, h - band_h + h * 0.045, 0.8,
                 (120, 200, 255), 1)
            _put(frame, slide["title"], w * 0.06, h - band_h + h * 0.115, 1.8,
                 (245, 245, 245), 3)
            if slide["caption"]:
                _put(frame, slide["caption"], w * 0.06,
                     h - band_h + h * 0.165, 0.7, (205, 205, 205), 2)
        else:
            _put(frame, ATTRACT_TITLE, w * 0.06, h - band_h + h * 0.105, 1.8,
                 (245, 245, 245), 3)
        # Sized to be read from across the hall, not from in front of the
        # exhibit: by the time small type here is legible you are already
        # close enough not to need the instruction.
        _put(frame, ATTRACT_PROMPT, w * 0.06, h - h * 0.035, 1.5,
             (120, 200, 255), 2)

        # Slide position, bottom-right. Dots for a handful of slides; past
        # ATTRACT_MAX_DOTS they stop being readable as positions and a
        # counter says the same thing in the same space.
        n = len(self.slides)
        y = int(h - h * 0.045)
        if n > ATTRACT_MAX_DOTS:
            text = f"{index + 1} / {n}"
            (tw, _th), _ = cv2.getTextSize(text, FONT, 0.6, 2)
            _put(frame, text, w - w * 0.06 - tw, y + 5, 0.6, (200, 200, 200),
                 2)
            return
        dot_r = max(int(h * 0.006), 2)
        gap = dot_r * 4
        x = w - w * 0.06 - gap * (n - 1)
        for i in range(n):
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
