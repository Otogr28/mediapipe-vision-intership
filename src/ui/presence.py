"""Is somebody standing in front of the exhibit?

The question attract mode turns on (see ``ui/attract.py``): with nobody there
the display runs a slideshow, and when a visitor walks up it greets them and
goes live. Getting that wrong in either direction is visible from across the
hall, so the answer is built from three signals rather than one:

1. **A tracked hand.** Free — the hand detector runs every frame anyway — and
   unambiguous. Somebody with a hand in frame is a visitor.
2. **Motion against a slowly-learned background.** This is the signal that
   catches the normal case: a person walking up with their hands down, who
   the hand detector cannot see at all. The frame is reduced to a
   ``PRESENCE_GRID_W``-wide grayscale thumbnail first, so the whole thing
   costs a fraction of a millisecond.
3. **A detected pose**, when some other feature already has body inference
   running. Never turned on *for* presence — pose is the app's biggest CPU
   cost and motion answers the same question for free.

The background is an EMA that adapts **only while nobody is present**. That
one detail is what makes a visitor who walks up and then stands perfectly
still keep registering, instead of dissolving into the background a few
seconds after they stop moving — which is exactly when they are reading the
screen and most need the exhibit to stay awake.

The exception is the first ``PRESENCE_WARMUP_S``, where the background is
learned fast and motion is ignored entirely. Cameras hand back a black or
half-exposed frame or two on open; seeded as the background, every later
frame reads as motion. Somebody who happens to be standing there during the
warm-up is learned as scenery, and is then noticed the moment they move or
raise a hand.

Distance is handled by the size of the disturbance rather than by any depth
estimate: somebody at the display fills a large part of the frame, somebody
crossing the corridor behind them does not. Hence two thresholds, a strict
one to wake up and a loose one to stay awake.
"""

import time

import cv2
import numpy as np

from config import (PRESENCE_BG_TAU_S, PRESENCE_ENTER_FRAC, PRESENCE_ENTER_S,
                    PRESENCE_EXIT_FRAC, PRESENCE_GRID_W, PRESENCE_PIXEL_DELTA,
                    PRESENCE_WARMUP_S)


class PresenceDetector:
    """Rolling answer to "is anybody there?".

    Call :meth:`update` once per frame with whatever the pipeline already
    has. Read :attr:`present` (hysteretic, instantaneous) and
    :attr:`motion_frac` (the raw evidence, for the debug HUD).

    The caller owns how long absence must last before acting on it — the
    manager holds the exhibit live for ``ATTRACT_IDLE_S`` after the last
    sighting, which is what absorbs a visitor briefly stepping out of frame.
    """

    def __init__(self):
        self.present = False
        self.motion_frac = 0.0
        # What last asserted presence: "hand", "pose", "motion" or None.
        self.source = None
        self._bg = None
        self._enter_since = None
        self._last_t = None
        self._first_t = None

    def _thumbnail(self, frame):
        h, w = frame.shape[:2]
        gh = max(int(round(PRESENCE_GRID_W * h / w)), 1)
        small = cv2.resize(frame, (PRESENCE_GRID_W, gh),
                           interpolation=cv2.INTER_AREA)
        if small.ndim == 3:
            small = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        return small.astype(np.float32)

    def update(self, frame, hand_result=None, pose_landmarks=None, now=None):
        """Advance one frame; returns :attr:`present`.

        ``frame`` may be None (no motion signal available this frame) — the
        hand and pose signals still work, which is what keeps the detector
        usable from a test or a mock backend with no camera.
        """
        if now is None:
            now = time.monotonic()
        dt = 0.0 if self._last_t is None else max(now - self._last_t, 0.0)
        self._last_t = now
        if self._first_t is None:
            self._first_t = now
        warming = (now - self._first_t) < PRESENCE_WARMUP_S

        has_hand = (hand_result is not None
                    and len(hand_result.hand_landmarks) > 0)
        has_pose = pose_landmarks is not None

        if frame is not None:
            small = self._thumbnail(frame)
            if self._bg is None or self._bg.shape != small.shape:
                self._bg = small.copy()
            self.motion_frac = float(
                np.count_nonzero(
                    np.abs(small - self._bg) > PRESENCE_PIXEL_DELTA)
            ) / small.size
            if (warming or not self.present) and dt > 0.0:
                # Learn the empty room, and ONLY the empty room: adapting
                # while somebody is standing there would quietly absorb them.
                # The warm-up learns fast, to get off whatever the camera
                # handed back as its first frame.
                tau = 0.3 if warming else PRESENCE_BG_TAU_S
                self._bg += (small - self._bg) * min(dt / tau, 1.0)

        if has_hand or has_pose:
            self.present = True
            self.source = "hand" if has_hand else "pose"
            self._enter_since = None
            return self.present

        if warming:
            # Motion means nothing yet — the background is still settling.
            return self.present

        if self.motion_frac >= PRESENCE_ENTER_FRAC:
            # A door swinging or a light switching also moves pixels, so the
            # evidence has to hold before it counts as somebody arriving.
            if self._enter_since is None:
                self._enter_since = now
            if now - self._enter_since >= PRESENCE_ENTER_S:
                self.present = True
                self.source = "motion"
        else:
            self._enter_since = None
            if self.present and self.motion_frac < PRESENCE_EXIT_FRAC:
                self.present = False
                self.source = None

        return self.present

    def to_state(self):
        """Debug-block payload: what the exhibit thinks it can see."""
        return {
            "present": self.present,
            "motion": round(self.motion_frac, 4),
            "source": self.source,
        }
