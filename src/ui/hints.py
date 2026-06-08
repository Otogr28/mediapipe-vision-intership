"""Onboarding overlays: startup splash + bottom-right pinch hint.

Both reuse :func:`draw_pinch_hand`, which renders a real 21-landmark hand
(MediaPipe's hand topology) posed mid-pinch: the middle, ring, and pinky
fingers are curled into a loose fist while the index and thumb extend and
animate together. Drawing it from the same skeleton the app already draws
for live hands keeps the demo unmistakably "a hand".

Neither class reads detection results directly — `UIManager` feeds them the
small amount of state they need (elapsed time is tracked internally, person
presence and "has interacted" come from the manager).
"""

import math
import time

import cv2
import numpy as np

from config import (
    HINT_PINCH_PERIOD_S,
    HINT_TEXT,
    HINT_TIMEOUT_S,
    INTRO_DURATION_S,
    INTRO_FADE_S,
    INTRO_SUBTITLE,
    INTRO_TITLE,
)

FONT = cv2.FONT_HERSHEY_SIMPLEX

# Stylized-hand palette (BGR — these overlays are drawn on dark panels).
SKIN = (188, 206, 236)       # soft warm skin tone
SKIN_EDGE = (60, 70, 92)     # darker outline for definition
NAIL = (220, 232, 250)       # fingertip highlight
GLOW = (170, 250, 255)       # pinch "tap" accent

# Hand template in normalised coords (x right, y down), following MediaPipe's
# hand landmark indices: 0 wrist, 1-4 thumb, 5-8 index, 9-12 middle,
# 13-16 ring, 17-20 pinky. The three non-pinching fingers are curled so the
# hand reads as a fist with only the index + thumb extended. Landmarks 4
# (thumb tip) and 8 (index tip) are computed per-frame for the animation.
_HAND_BASE = {
    0:  (0.50, 1.05),   # wrist
    1:  (0.68, 0.84),   # thumb CMC
    2:  (0.80, 0.62),   # thumb MCP (out to the right, clear of the fist)
    3:  (0.76, 0.42),   # thumb IP
    5:  (0.60, 0.54),   # index MCP
    6:  (0.61, 0.37),   # index PIP
    7:  (0.61, 0.27),   # index DIP
    9:  (0.48, 0.52),   # middle MCP
    10: (0.48, 0.39),   # middle PIP
    11: (0.50, 0.47),   # middle DIP (curled back)
    12: (0.50, 0.55),   # middle TIP (curled back)
    13: (0.37, 0.54),   # ring MCP
    14: (0.36, 0.42),   # ring PIP
    15: (0.38, 0.49),   # ring DIP (curled back)
    16: (0.39, 0.57),   # ring TIP (curled back)
    17: (0.27, 0.60),   # pinky MCP
    18: (0.26, 0.49),   # pinky PIP
    19: (0.28, 0.55),   # pinky DIP (curled back)
    20: (0.30, 0.62),   # pinky TIP (curled back)
}

_HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17),
]
_PALM = [0, 1, 5, 9, 13, 17]


def _lerp(a, b, t):
    return a + (b - a) * t


def _capsule(frame, p0, p1, radius, color):
    """Thick rounded segment (line + end caps)."""
    p0 = (int(p0[0]), int(p0[1]))
    p1 = (int(p1[0]), int(p1[1]))
    cv2.line(frame, p0, p1, color, radius * 2, cv2.LINE_AA)
    cv2.circle(frame, p0, radius, color, -1, cv2.LINE_AA)
    cv2.circle(frame, p1, radius, color, -1, cv2.LINE_AA)


def draw_pinch_hand(frame, cx, cy, s, openness):
    """Draw a real 21-landmark hand mid-pinch, centred near ``(cx, cy)``.

    ``s`` is the approximate hand height in pixels; ``openness`` in
    ``[0, 1]`` sets how far the thumb and index are apart (0 = touching,
    1 = wide open). A glow ring pulses at the pinch point as they meet.
    """
    t = max(0.0, min(1.0, openness))

    pts_n = dict(_HAND_BASE)
    # Index tip: straight up when open, curling down to meet the thumb closed.
    pts_n[8] = (_lerp(0.605, 0.59, t), _lerp(0.33, 0.15, t))
    # Thumb tip: swings out to the right when open, meets the index when closed.
    pts_n[4] = (_lerp(0.605, 0.71, t), _lerp(0.33, 0.27, t))

    def to_px(p):
        return (cx + (p[0] - 0.5) * s, cy + (p[1] - 0.55) * s)

    pts = {i: to_px(p) for i, p in pts_n.items()}
    rf = max(int(0.072 * s), 2)

    palm = np.array([pts[i] for i in _PALM], dtype=np.float32)
    centroid = palm.mean(axis=0)

    def draw_pass(radius, color, palm_grow):
        hull = cv2.convexHull(
            ((palm - centroid) * palm_grow + centroid).astype(np.int32)
        )
        cv2.fillConvexPoly(frame, hull, color, cv2.LINE_AA)
        for a, b in _HAND_CONNECTIONS:
            _capsule(frame, pts[a], pts[b], radius, color)
        for p in pts.values():
            cv2.circle(frame, (int(p[0]), int(p[1])), radius, color, -1, cv2.LINE_AA)

    # Outline pass (slightly fatter + grown palm) then the skin fill on top.
    draw_pass(rf + 2, SKIN_EDGE, 1.14)
    draw_pass(rf, SKIN, 1.0)

    # Fingertip highlights on the two active fingers.
    for idx in (4, 8):
        cv2.circle(frame, (int(pts[idx][0]), int(pts[idx][1])),
                   max(rf - 2, 1), NAIL, -1, cv2.LINE_AA)

    # Pinch glow as the fingertips meet.
    closeness = 1.0 - t
    if closeness > 0.45:
        a = (closeness - 0.45) / 0.55  # 0..1 as it finishes closing
        mid = (int((pts[4][0] + pts[8][0]) / 2),
               int((pts[4][1] + pts[8][1]) / 2))
        ring_r = max(int((0.08 + 0.16 * a) * s), 1)
        cv2.circle(frame, mid, ring_r, GLOW, 2, cv2.LINE_AA)
        cv2.circle(frame, mid, max(int(0.04 * s), 2), GLOW, -1, cv2.LINE_AA)


def _pinch_openness(start, period):
    """Looping open->close->open value in [0, 1] driven by the clock."""
    phase = ((time.monotonic() - start) % period) / period
    return 0.5 * (1.0 + math.cos(2.0 * math.pi * phase))


def _put_centered(frame, text, cx, y, scale, color, thick):
    (tw, _th), _ = cv2.getTextSize(text, FONT, scale, thick)
    cv2.putText(frame, text, (int(cx - tw / 2), int(y)), FONT, scale,
                color, thick, cv2.LINE_AA)


def _wrap(text, scale, thick, max_w):
    """Greedy word-wrap so a label fits within ``max_w`` pixels."""
    words = text.split()
    lines, cur = [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        (tw, _), _ = cv2.getTextSize(trial, FONT, scale, thick)
        if tw <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


class IntroOverlay:
    """Startup splash demonstrating the pinch gesture for a few seconds."""

    def __init__(self, frame_w, frame_h):
        self.w = frame_w
        self.h = frame_h
        self._start = time.monotonic()

    @property
    def active(self):
        return (time.monotonic() - self._start) < INTRO_DURATION_S

    def _opacity(self):
        elapsed = time.monotonic() - self._start
        if elapsed >= INTRO_DURATION_S:
            return 0.0
        fade_in = elapsed / INTRO_FADE_S
        fade_out = (INTRO_DURATION_S - elapsed) / INTRO_FADE_S
        return max(0.0, min(1.0, fade_in, fade_out))

    def draw(self, frame):
        op = self._opacity()
        if op <= 0.0:
            return

        w, h = self.w, self.h
        cx = w / 2.0
        # Dim the live camera so the splash reads as an overlay, not a wipe.
        layer = cv2.addWeighted(frame, 0.30, np.zeros_like(frame), 0.0, 0.0)

        _put_centered(layer, INTRO_TITLE, cx, h * 0.22, 1.4, (255, 255, 255), 3)
        _put_centered(layer, INTRO_SUBTITLE, cx, h * 0.22 + 38, 0.6, (200, 200, 200), 1)

        s = min(w, h) * 0.20
        draw_pinch_hand(layer, cx, h * 0.52, s,
                        _pinch_openness(self._start, HINT_PINCH_PERIOD_S))
        _put_centered(layer, HINT_TEXT, cx, h * 0.52 + s * 0.72, 0.8, (255, 255, 255), 2)

        # Countdown bar.
        elapsed = time.monotonic() - self._start
        prog = max(0.0, min(1.0, elapsed / INTRO_DURATION_S))
        bar_w = int(w * 0.40)
        bx, by, bh = int(cx - bar_w / 2), int(h * 0.86), 8
        cv2.rectangle(layer, (bx, by), (bx + bar_w, by + bh), (80, 80, 80), -1)
        cv2.rectangle(layer, (bx, by), (bx + int(bar_w * prog), by + bh), (0, 200, 255), -1)

        cv2.addWeighted(layer, op, frame, 1.0 - op, 0.0, frame)


class PinchHint:
    """Bottom-right reminder shown while a person is detected and has not
    interacted yet.

    Retires permanently after the first interaction, and also auto-expires
    `HINT_TIMEOUT_S` seconds after it first appears — so once it has had its
    say it never comes back, whether or not the user tried the gesture."""

    PANEL_W = 250
    PANEL_H = 185
    MARGIN = 24

    def __init__(self, frame_w, frame_h):
        self.w = frame_w
        self.h = frame_h
        self._anim_start = time.monotonic()
        self._first_shown = None
        self._expired = False
        self._visible = False

    def update(self, person_detected, has_interacted):
        if self._expired or has_interacted:
            self._expired = True   # latch: never show again
            self._visible = False
            return

        if not person_detected:
            self._visible = False
            return

        now = time.monotonic()
        if self._first_shown is None:
            self._first_shown = now
        elif now - self._first_shown > HINT_TIMEOUT_S:
            self._expired = True
            self._visible = False
            return

        self._visible = True

    @property
    def visible(self):
        return self._visible

    def draw(self, frame):
        if not self._visible:
            return

        x1 = self.w - self.PANEL_W - self.MARGIN
        y1 = self.h - self.PANEL_H - self.MARGIN
        x2, y2 = x1 + self.PANEL_W, y1 + self.PANEL_H

        # Semi-transparent panel (blending leaves everything outside the
        # rect untouched since `overlay` only differs there).
        overlay = frame.copy()
        cv2.rectangle(overlay, (x1, y1), (x2, y2), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.5, frame, 0.5, 0.0, frame)
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 200, 255), 2)

        cx = (x1 + x2) / 2.0
        draw_pinch_hand(frame, cx, y1 + 70, 70,
                        _pinch_openness(self._anim_start, HINT_PINCH_PERIOD_S))

        lines = _wrap(HINT_TEXT, 0.5, 1, self.PANEL_W - 24)
        ty = y1 + 140
        for line in lines:
            _put_centered(frame, line, cx, ty, 0.5, (235, 235, 235), 1)
            ty += 22
