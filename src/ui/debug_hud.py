"""On-frame debug HUD, enabled with ``HALL_DEBUG=1``.

A bottom-left panel showing exactly what the pinch pipeline sees, so
thresholds can be tuned with evidence instead of feel: per hand the machine
state, the filtered ratio against both thresholds (as a bar with tick
marks), the continuous progress and the cursor; globally the detection
result age (the same value the cursor extrapolation uses), the detector's
callback rate, the render rate and the active hand backend.

This module deliberately imports ``gestures`` and ``detectors`` directly —
it is a debug view of those two modules' internals, and routing their
values through UIManager would add coupling for no benefit.
"""

import time

import cv2

from config import (FIST_CLOSE_RATIO, FIST_RELEASE_RATIO, GESTURE_MODE,
                    HALL_INFERENCE, PINCH_CLOSE_RATIO, PINCH_RELEASE_RATIO,
                    PRESENCE_ENTER_FRAC, PRESENCE_ENTER_SPAN,
                    PRESENCE_HAND_SPAN)
from detection import detectors, gestures

FONT = cv2.FONT_HERSHEY_SIMPLEX

PANEL_W = 410
LINE_H = 20
PAD = 10
MARGIN = 12
BAR_W = 170
BAR_H = 8
BAR_MAX_RATIO = 1.5   # bar full scale, in ratio units

COL_TEXT = (230, 230, 230)
COL_DIM = (170, 170, 170)
COL_BAR_BG = (70, 70, 70)
COL_CLOSED = (140, 255, 150)
COL_OPEN = (60, 200, 255)
COL_TICK = (255, 255, 255)


class DebugHUD:
    """Draw-only overlay; construct once, call ``draw(frame)`` dead-last so
    it sits above every other layer. Self-measures the render rate from its
    own draw interval (EMA), so it needs no update() hook."""

    def __init__(self, frame_w, frame_h):
        self.w = frame_w
        self.h = frame_h
        self._last_draw_t = None
        self._dt_ema = 0.0
        # Precomputed bar tick positions (constant thresholds).
        self._tick_close = int(BAR_W * PINCH_CLOSE_RATIO / BAR_MAX_RATIO)
        self._tick_release = int(BAR_W * PINCH_RELEASE_RATIO / BAR_MAX_RATIO)

    def draw(self, frame, presence=None):
        """``presence`` is ``PresenceDetector.to_state()`` when attract mode
        is running — the measured blob size, blob height and hand size next
        to the thresholds they have to clear, which is what makes the "is
        somebody CLOSE" gates tunable against the real room."""
        now = time.monotonic()
        if self._last_draw_t is not None:
            dt = now - self._last_draw_t
            self._dt_ema = dt if self._dt_ema == 0.0 else \
                0.9 * self._dt_ema + 0.1 * dt
        self._last_draw_t = now

        infos = gestures.pinch_infos()
        lines = 2 + 3 * len(infos) + (1 if presence is not None else 0)
        panel_h = PAD * 2 + LINE_H * lines
        x0 = MARGIN
        y1 = self.h - MARGIN
        y0 = max(0, y1 - panel_h)

        # Darken the panel region in place (ROI halving — no full-frame
        # copy; this may run on the Jetson).
        roi = frame[y0:y1, x0:x0 + PANEL_W]
        roi[:] = roi // 2

        render_fps = 1.0 / self._dt_ema if self._dt_ema > 0.0 else 0.0
        ty = y0 + PAD + 14
        cv2.putText(frame,
                    f"render {render_fps:4.0f} fps   "
                    f"hand det {detectors.hand_fps():4.0f} fps   "
                    f"age {gestures.result_age_s() * 1000:3.0f} ms",
                    (x0 + PAD, ty), FONT, 0.45, COL_TEXT, 1, cv2.LINE_AA)
        ty += LINE_H
        cv2.putText(frame,
                    f"backend {HALL_INFERENCE}   gesture {GESTURE_MODE}"
                    f"   pinch <{PINCH_CLOSE_RATIO} >{PINCH_RELEASE_RATIO}"
                    f"   fist <{FIST_CLOSE_RATIO} >{FIST_RELEASE_RATIO}",
                    (x0 + PAD, ty), FONT, 0.38, COL_DIM, 1, cv2.LINE_AA)

        if presence is not None:
            # Both gates on one line, each next to the threshold it has to
            # clear: blob area, blob height and hand size are what decide
            # "somebody is CLOSE", and tuning them means watching these three
            # numbers while walking towards and away from the camera.
            ty += LINE_H
            cv2.putText(frame,
                        f"presence {'YES' if presence['present'] else 'no '}"
                        f" via {presence['source'] or '--'}"
                        f"   blob {presence['blob']:.3f}>{PRESENCE_ENTER_FRAC}"
                        f"  tall {presence['span']:.2f}>{PRESENCE_ENTER_SPAN}"
                        f"  hand {presence['hand']:.2f}>{PRESENCE_HAND_SPAN}"
                        f"  still {presence.get('still', 0.0):.0f}s",
                        (x0 + PAD, ty), FONT, 0.38,
                        COL_CLOSED if presence["present"] else COL_DIM, 1,
                        cv2.LINE_AA)

        for hid, m in infos:
            ratio = m.ratio
            ty += LINE_H
            rtxt = f"{ratio:.2f}" if ratio is not None else "--"
            cv2.putText(frame,
                        f"{hid}: {m.state:<9} ratio {rtxt}  "
                        f"prog {m.progress:.2f}",
                        (x0 + PAD, ty), FONT, 0.45, COL_TEXT, 1, cv2.LINE_AA)
            # Ratio bar with tick marks at the two thresholds.
            ty += LINE_H
            bx, by = x0 + PAD, ty - BAR_H
            cv2.rectangle(frame, (bx, by), (bx + BAR_W, by + BAR_H),
                          COL_BAR_BG, -1)
            if ratio is not None:
                fill = int(min(ratio / BAR_MAX_RATIO, 1.0) * BAR_W)
                col = COL_CLOSED if m.closed else COL_OPEN
                cv2.rectangle(frame, (bx, by), (bx + fill, by + BAR_H),
                              col, -1)
            for tick in (self._tick_close, self._tick_release):
                cv2.line(frame, (bx + tick, by - 2),
                         (bx + tick, by + BAR_H + 2), COL_TICK, 1)
            ty += LINE_H
            # Both gestures in their OWN units, next to the combined ratio
            # above: this is the readout the fist thresholds are tuned
            # against, and it also shows which gesture won in "either" mode.
            ptxt = ("--" if m.pinch_ratio is None
                    else f"{m.pinch_ratio:.2f}")
            ftxt = "--" if m.fist_ratio is None else f"{m.fist_ratio:.2f}"
            cv2.putText(frame,
                        f"pinch {ptxt}  fist {ftxt}   "
                        f"cursor ({m.cursor[0]:4.0f},{m.cursor[1]:4.0f})  "
                        f"seen {(now - m.last_seen) * 1000:3.0f} ms",
                        (x0 + PAD, ty), FONT, 0.4, COL_DIM, 1, cv2.LINE_AA)
