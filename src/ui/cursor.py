"""Always-on pinch cursor overlay.

One cursor per tracked hand, drawn at the pinch point the detector actually
uses (thumb-tip-anchored, One-Euro-smoothed, latency-compensated — see
detection/gestures.py). A ring fills with the continuous pinch progress
(0 at the release threshold, 1 at the close threshold — Meta-style pinch
strength as a UI signal) and a short expanding flash confirms each
registered click. This closes the feedback loop that made pinching feel
rough: the user steers the dot they can see, and every state the machine
passes through is visible the frame it happens.
"""

import time

import cv2

from detection import gestures

# Palette (BGR) — visuals stay module-local (hints.py / slingshot precedent).
COL_IDLE = (180, 180, 180)     # neutral ring, hand open
COL_CLOSING = (60, 200, 255)   # amber while the fingers close
COL_HELD = (140, 255, 150)     # green while the pinch is held
COL_FLASH = (255, 255, 255)    # click confirmation ring
COL_UNDER = (25, 25, 25)       # dark under-stroke for video readability

RING_R = 14        # progress ring radius (px)
DOT_R = 4          # centre dot radius (px)
FLASH_FRAMES = 6   # duration of the click flash
FLASH_GROW_PX = 18 # how far the flash ring expands
STALE_S = 0.2      # hide machines not updated this recently (grace ghosts)


class PinchCursor:
    """Draws the per-hand pinch cursors. Reads the gesture snapshot only —
    construct once and call ``draw(frame)`` after the scene, before the
    onboarding overlays."""

    def __init__(self, frame_w, frame_h):
        self.w = frame_w
        self.h = frame_h
        self._flash = {}   # hand_id -> frames left of the click flash

    def draw(self, frame):
        now = time.monotonic()
        live = set()
        for hid, m in gestures.pinch_infos():
            # A machine inside the tracking-grace window but without fresh
            # data would freeze a ghost cursor on screen — skip it.
            if now - m.last_seen > STALE_S:
                continue
            live.add(hid)
            if m.pinching:
                self._flash[hid] = FLASH_FRAMES

            x, y = int(m.cursor[0]), int(m.cursor[1])
            if not (0 <= x < self.w and 0 <= y < self.h):
                continue
            progress = m.progress
            if m.closed:
                color = COL_HELD
            elif progress > 0.0:
                color = COL_CLOSING
            else:
                color = COL_IDLE

            # Faint base ring, always visible (this IS the cursor).
            cv2.circle(frame, (x, y), RING_R, COL_UNDER, 4, cv2.LINE_AA)
            cv2.circle(frame, (x, y), RING_R, COL_IDLE, 1, cv2.LINE_AA)
            # Progress arc fills clockwise from 12 o'clock as fingers close.
            if progress > 0.0:
                end = int(-90 + 360 * progress)
                cv2.ellipse(frame, (x, y), (RING_R, RING_R), 0, -90, end,
                            COL_UNDER, 5, cv2.LINE_AA)
                cv2.ellipse(frame, (x, y), (RING_R, RING_R), 0, -90, end,
                            color, 3, cv2.LINE_AA)
            # Centre dot; slightly larger and colored while held.
            r = DOT_R + (2 if m.closed else 0)
            cv2.circle(frame, (x, y), r + 2, COL_UNDER, -1, cv2.LINE_AA)
            cv2.circle(frame, (x, y), r, color, -1, cv2.LINE_AA)

            # Click flash: an expanding, thinning ring for a few frames.
            f = self._flash.get(hid, 0)
            if f > 0:
                t = f / FLASH_FRAMES
                fr = int(RING_R + (1.0 - t) * FLASH_GROW_PX)
                cv2.circle(frame, (x, y), fr, COL_FLASH,
                           max(1, int(3 * t)), cv2.LINE_AA)
                self._flash[hid] = f - 1

        # Drop flash counters of departed hands.
        self._flash = {h: v for h, v in self._flash.items()
                       if h in live and v > 0}
