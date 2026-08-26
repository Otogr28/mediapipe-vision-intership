"""Is somebody standing CLOSE TO the exhibit?

The question attract mode turns on (see ``ui/attract.py``): with nobody there
the display runs a slideshow, and when a visitor walks up it greets them and
goes live. Getting it wrong in either direction is visible from across the
hall, so the answer is built from three signals rather than one:

1. **A tracked hand.** Free — the hand detector runs every frame anyway — and
   unambiguous.
2. **Motion against a slowly-learned background.** This is the signal that
   catches the normal case: a person walking up with their hands down, who
   the hand detector cannot see at all. The frame is reduced to a
   ``PRESENCE_GRID_W``-wide grayscale thumbnail first, so the whole thing
   costs a fraction of a millisecond.
3. **A detected pose**, when some other feature already has body inference
   running. Never turned on *for* presence — pose is the app's biggest CPU
   cost and motion answers the same question for free.

**Every one of them is gated on size**, because the exhibit is armed for
somebody within reach of it and not for the corridor behind them. A camera
has no depth, but a fixed camera does not need one: things get bigger as they
come closer, so how much of the frame a person occupies *is* the distance
estimate. Hence a hand must measure ``PRESENCE_HAND_SPAN`` before it counts,
and the motion signal is judged on the largest connected **blob** rather than
on a raw count of changed pixels.

That blob is the part worth understanding. Changed pixels are grouped, the
biggest group is measured, and it has to be both large and **tall** —
``PRESENCE_ENTER_SPAN`` of the frame's height. Height is what separates near
from far: somebody at the screen runs from the bottom edge to near the top,
while the same person at the end of the corridor is a short patch no matter
how briskly they move. It also throws out things that are not people at all,
since a flickering lamp, a monitor behind or leaves in a window scatter
changes over the frame without ever forming one tall blob. The bare
changed-fraction test this replaced could not tell any of that apart, and
woke the exhibit for all of it.

The background is an EMA that adapts **only while nobody is present**. That
one detail is what makes a visitor who walks up and then stands perfectly
still keep registering, instead of dissolving into the background a few
seconds after they stop moving — which is exactly when they are reading the
screen and most need the exhibit to stay awake.

That same detail creates a deadlock the detector must break itself out of:
if the whole picture shifts while somebody is present (the camera's
auto-exposure re-adapting around them, the corridor light changing), the
frozen background is stale when they leave — the empty room reads as one
frame-wide blob, presence never releases, and the background can never
re-learn because presence never releases. The way out is that such a
difference is DEAD: consecutive thumbnails are identical, while a standing
person's edges flicker every few seconds however still they hold. Presence
held ``PRESENCE_STATIC_RELEASE_S`` with zero frame-to-frame activity is
therefore ruled scenery — the background re-seeds from the current frame
and presence releases (see ``config.PRESENCE_STATIC_RELEASE_S``).

The exception is the first ``PRESENCE_WARMUP_S``, where the background is
learned fast and motion is ignored entirely. Cameras hand back a black or
half-exposed frame or two on open; seeded as the background, every later
frame reads as motion. Somebody who happens to be standing there during the
warm-up is learned as scenery, and is then noticed the moment they move or
raise a hand.
"""

import time

import cv2
import numpy as np

from config import (PRESENCE_BG_TAU_S, PRESENCE_ENTER_FRAC, PRESENCE_ENTER_S,
                    PRESENCE_ENTER_SPAN, PRESENCE_EXIT_FRAC,
                    PRESENCE_EXIT_SPAN, PRESENCE_GRID_W,
                    PRESENCE_HAND_EXIT_SPAN, PRESENCE_HAND_SPAN, PRESENCE_MODE,
                    PRESENCE_PIXEL_DELTA, PRESENCE_POSE_EXIT_SPAN,
                    PRESENCE_POSE_SPAN, PRESENCE_STATIC_RELEASE_S,
                    PRESENCE_WARMUP_S)

# Speckle filter for the motion mask. On a 64px-wide thumbnail one pixel is a
# big chunk of the room, so a 3x3 open only removes isolated sensor noise —
# but that noise is exactly what would otherwise glue two far-apart patches
# into one "tall" blob through a diagonal chain.
_OPEN_KERNEL = np.ones((3, 3), np.uint8)


def _hand_span(hand_result):
    """Longest side of the biggest hand's bounding box, in frame fractions.

    0.0 when there is no hand. Landmarks are normalized to the frame, so this
    is directly comparable to ``PRESENCE_HAND_SPAN`` without knowing the
    capture resolution — and it is the same number whichever backend
    (MediaPipe or the ONNX one) produced the landmarks.
    """
    if hand_result is None or not hand_result.hand_landmarks:
        return 0.0
    best = 0.0
    for lms in hand_result.hand_landmarks:
        if not lms:
            continue
        xs = [lm.x for lm in lms]
        ys = [lm.y for lm in lms]
        best = max(best, max(xs) - min(xs), max(ys) - min(ys))
    return float(best)


def _pose_span(pose_landmarks):
    """Height of the visible pose landmarks' bounding box, in frame
    fractions. 0.0 when there is no pose.

    Height rather than the longest side: a person is tall, and a raised arm
    would otherwise make a distant visitor measure as wide as a near one.
    """
    if not pose_landmarks:
        return 0.0
    ys = [lm.y for lm in pose_landmarks
          if getattr(lm, "visibility", 1.0) >= 0.5]
    if len(ys) < 2:
        return 0.0
    return float(max(ys) - min(ys))


class PresenceDetector:
    """Rolling answer to "is anybody standing at this thing?".

    Call :meth:`update` once per frame with whatever the pipeline already
    has. Read :attr:`present` (hysteretic, instantaneous) and the measured
    evidence (:attr:`blob_frac`, :attr:`blob_span`, :attr:`hand_span`) for
    the debug HUD — those three are what you tune the thresholds against on
    the device, since no synthetic test can tell you what a real hall looks
    like to a real camera.

    The caller owns how long absence must last before acting on it — the
    manager holds the exhibit live for ``ATTRACT_IDLE_S`` after the last
    sighting, which is what absorbs a visitor briefly stepping out of frame.
    """

    def __init__(self, mode=None):
        # "hand" (default, config.PRESENCE_MODE): only the hand signal may
        # assert presence — the picture is never consulted, so none of the
        # background machinery below runs. "full": hand + motion + pose.
        self.mode = mode if mode is not None else PRESENCE_MODE
        self.present = False
        # Raw changed-pixel fraction. No longer a threshold input — kept
        # because it is the one number that says "the camera is producing a
        # picture at all", which is worth seeing on the HUD.
        self.motion_frac = 0.0
        # The largest connected blob of change: its area and its height, both
        # as fractions of the frame. These are what decide the motion signal.
        self.blob_frac = 0.0
        self.blob_span = 0.0
        self.hand_span = 0.0
        self.pose_span = 0.0
        # What last asserted presence: "hand", "pose", "motion" or None.
        self.source = None
        # Seconds since the picture last changed frame-to-frame — the
        # "is this difference alive" number behind the static release.
        self.still_s = 0.0
        self._bg = None
        self._prev = None
        self._last_activity_t = None
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

    def _measure_motion(self, small):
        """Fill in ``motion_frac`` / ``blob_frac`` / ``blob_span``."""
        diff = np.abs(small - self._bg) > PRESENCE_PIXEL_DELTA
        self.motion_frac = float(np.count_nonzero(diff)) / diff.size

        mask = cv2.morphologyEx(diff.astype(np.uint8), cv2.MORPH_OPEN,
                                _OPEN_KERNEL)
        n, _labels, stats, _cent = cv2.connectedComponentsWithStats(mask, 8)
        if n <= 1:
            self.blob_frac = 0.0
            self.blob_span = 0.0
            return
        # Row 0 is the background label; the rest are blobs of change.
        areas = stats[1:, cv2.CC_STAT_AREA]
        biggest = 1 + int(np.argmax(areas))
        self.blob_frac = float(stats[biggest, cv2.CC_STAT_AREA]) / mask.size
        self.blob_span = float(stats[biggest, cv2.CC_STAT_HEIGHT]) \
            / mask.shape[0]

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

        self.hand_span = _hand_span(hand_result)
        self.pose_span = _pose_span(pose_landmarks)

        # Hand-only mode (the default, see config.PRESENCE_MODE): the picture
        # is never consulted, so the background, the blobs, the activity
        # tracker and the static release all stay dormant. What remains is
        # exactly the operator's rule: a hand big enough in frame arms the
        # exhibit, its absence releases it, and UIManager's ATTRACT_IDLE_S
        # turns that absence into the slideshow.
        use_motion = self.mode != "hand"

        if frame is not None and use_motion:
            small = self._thumbnail(frame)
            if self._bg is None or self._bg.shape != small.shape:
                self._bg = small.copy()
            self._measure_motion(small)

            # Frame-to-frame activity: is the picture ALIVE, regardless of
            # how far it sits from the learned background? Same delta and
            # speckle filter as the motion mask, so "still" means still to
            # the same instrument that asserted the presence.
            if self._prev is None or self._prev.shape != small.shape:
                self._last_activity_t = now
            else:
                moved = (np.abs(small - self._prev)
                         > PRESENCE_PIXEL_DELTA).astype(np.uint8)
                if cv2.morphologyEx(moved, cv2.MORPH_OPEN, _OPEN_KERNEL).any():
                    self._last_activity_t = now
            self._prev = small
            self.still_s = now - self._last_activity_t

            # The deadlock breaker (see the module docstring): presence held
            # by a difference that has shown no life whatsoever for
            # PRESENCE_STATIC_RELEASE_S is a lighting/exposure shift baked
            # into a stale background, not a person. Re-seed and release, so
            # the idle slideshow can come back instead of never. Only the
            # MOTION source can deadlock — hand and pose re-assert from the
            # detectors every frame and never consult the background — and
            # gating on it keeps a (phantom) hand from re-seeding the
            # background with a person baked in.
            if (self.present and self.source == "motion" and not warming
                    and self.still_s > PRESENCE_STATIC_RELEASE_S):
                self._bg = small.copy()
                self._measure_motion(small)
                self.present = False
                self.source = None
                self._enter_since = None

            if (warming or not self.present) and dt > 0.0:
                # Learn the empty room, and ONLY the empty room: adapting
                # while somebody is standing there would quietly absorb them.
                # The warm-up learns fast, to get off whatever the camera
                # handed back as its first frame.
                tau = 0.3 if warming else PRESENCE_BG_TAU_S
                self._bg += (small - self._bg) * min(dt / tau, 1.0)

        # Each signal is read against the strict threshold while absent and
        # the loose one while present. That is the hysteresis: it takes a
        # clear arrival to wake the exhibit, and a clear departure to release
        # it, with no band in between where it oscillates.
        near = not self.present
        # `> 0.0` first: no hand measures 0.0, and an exit gate of 0.0
        # ("any tracked hand holds presence") must not read that as a hand.
        hand_ok = self.hand_span > 0.0 and self.hand_span >= (
            PRESENCE_HAND_SPAN if near else PRESENCE_HAND_EXIT_SPAN)
        pose_ok = use_motion and self.pose_span >= (
            PRESENCE_POSE_SPAN if near else PRESENCE_POSE_EXIT_SPAN)
        motion_ok = use_motion and (
            self.blob_frac >= (PRESENCE_ENTER_FRAC if near
                               else PRESENCE_EXIT_FRAC)
            and self.blob_span >= (PRESENCE_ENTER_SPAN if near
                                   else PRESENCE_EXIT_SPAN))

        if hand_ok or pose_ok:
            # No dwell time on these two: a measurable hand or body is not
            # something a swinging door produces.
            self.present = True
            self.source = "hand" if hand_ok else "pose"
            self._enter_since = None
            return self.present

        if warming:
            # Motion means nothing yet — the background is still settling.
            # Hold whatever was decided rather than clearing it, so a hand
            # seen during warm-up is not dropped a frame later.
            return self.present

        if motion_ok:
            if self.present:
                # Already awake and still seeing a person-sized disturbance.
                self.source = "motion"
            else:
                # A door swinging or a light switching also moves pixels, so
                # the evidence has to hold before it counts as an arrival.
                if self._enter_since is None:
                    self._enter_since = now
                if now - self._enter_since >= PRESENCE_ENTER_S:
                    self.present = True
                    self.source = "motion"
        else:
            self._enter_since = None
            self.present = False
            self.source = None

        return self.present

    def to_state(self):
        """Debug-block payload: what the exhibit thinks it can see, and how
        big it measures — the numbers ``HALL_DEBUG=1`` puts on screen so the
        thresholds can be tuned against the actual room."""
        return {
            "present": self.present,
            "motion": round(self.motion_frac, 4),
            "blob": round(self.blob_frac, 4),
            "span": round(self.blob_span, 3),
            "hand": round(self.hand_span, 3),
            "source": self.source,
            # Seconds without any frame-to-frame change — the static-release
            # countdown. Watching it climb while the room is empty and
            # "present" reads YES is watching the latch being defused.
            "still": round(self.still_s, 1),
        }
