"""Exposure metered on the VISITOR, not on the room.

The exhibit camera faces a wall of windows and cannot be moved, so the visitor
stands in front of the brightest thing in the hall. A webcam's own automatic
exposure meters the whole frame, daylight wins by several stops, and the person
lands in silhouette — which is precisely the input MediaPipe's hand landmark
model cannot read.

The camera will not solve this for us. Logitech's RightLight (face-aware
metering) and the MX Brio's HDR live in their desktop software; over UVC on
Linux neither is exposed, and `cameractrls`, which is the most complete
reverse-engineering of Logitech's vendor controls, publishes only LED, FoV and
pan/tilt for these cameras. `backlight_compensation` is the one hardware lever,
and a coarse centre weighting does not swallow a six-stop window.

Fixing it by hand means pinning a manual exposure, and a pinned exposure does
not track daylight: a value chosen at noon is wrong by dusk. So this module is
the automatic metering the camera does not have. It is not a general-purpose
auto-exposure; it is narrower and better than one, because this application
already knows where the person is:

  1. **The hands**, when the detector has them — the exact thing that has to be
     readable, and MediaPipe already found them this frame at no extra cost.
  2. **The motion blob** from :mod:`ui.presence`, when it does not. This is the
     bootstrap that matters: a backlit visitor is a silhouette no landmark
     model can find, so metering on hands alone would deadlock — too dark to
     detect hands, no hands to meter on. A difference image does not care how
     dark somebody is, so the blob gets the picture into range and the hands
     take over from there as the finer target.
  3. **Nothing** — hold. An empty room is metered by nobody: adapting to it
     would just re-expose for the windows and undo the work.

Generic auto-exposure work (`uzh-rpg/active_camera_exposure_control`,
`MIT-Bilab/vo-autoexpose`) optimizes image gradient for feature tracking, which
is the robotics problem, not this one. Here the target is a mean luminance a
person is legible at, and the metering region is the whole trick.

Everything is off unless ``HALL_CAM_AE=1`` asks for it.
"""

import time

import cv2
import numpy as np

from capture import get_control, set_control

# V4L2 control ids, same ones `capture.CAMERA_CONTROLS` drives.
_AUTO_EXPOSURE = 0x009A0901
_EXPOSURE = 0x009A0902
_GAIN = 0x00980913
_EXPOSURE_MANUAL = 1   # V4L2_EXPOSURE_MANUAL


def _clamp(value, low, high):
    return max(low, min(high, value))


class SubjectExposure:
    """Drives exposure + gain to hold the visitor at a legible brightness.

    Call :meth:`update` once per frame with the mirrored camera frame and
    whatever the detectors found. The work is rate limited internally, so the
    per-frame cost when it is not its turn is a clock read.
    """

    def __init__(self, path, cfg):
        self.path = path
        self.cfg = cfg
        self.ok = False
        self.measured = None      # last smoothed ROI luminance, for the HUD
        self.source = "none"      # which ROI the last measurement came from
        self._smoothed = None
        self._next_t = 0.0
        self._hold_until = 0.0
        self._report_t = 0.0
        self._offered = "nothing"

        # Software metering only means anything in Manual: in any automatic
        # mode the camera owns exposure_time_absolute and reports it inactive,
        # so every write would be silently dropped.
        if set_control(path, _AUTO_EXPOSURE, _EXPOSURE_MANUAL) != _EXPOSURE_MANUAL:
            print("camera: auto-exposure could not be switched to manual — "
                  "software metering disabled")
            return
        self.exposure = get_control(path, _EXPOSURE)
        self.gain = get_control(path, _GAIN)
        if self.exposure is None or self.gain is None:
            print("camera: no exposure/gain control — software metering "
                  "disabled")
            return
        self.ok = True
        print("camera: metering exposure on the visitor "
              "(target %d, exposure %d-%d, gain <= %d)"
              % (cfg.target, cfg.exposure_min, cfg.exposure_max, cfg.gain_max),
              flush=True)

    # -- region of interest --------------------------------------------------

    @staticmethod
    def _hand_rect(hand_result):
        """Bounding box over every detected hand, normalized, or None."""
        hands = getattr(hand_result, "hand_landmarks", None) if hand_result \
            else None
        if not hands:
            return None
        xs = [lm.x for hand in hands for lm in hand]
        ys = [lm.y for hand in hands for lm in hand]
        if not xs:
            return None
        return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)

    def _roi(self, hand_result, blob_rect):
        rect = self._hand_rect(hand_result)
        if rect is not None:
            return rect, "hands"
        if blob_rect is not None:
            return blob_rect, "motion"
        return None, "none"

    def _measure(self, frame, rect):
        """Subject luminance inside ``rect``, or None if the crop is degenerate.

        This is a PERCENTILE, not a mean, and the difference is the whole
        problem. The region around a backlit visitor is bimodal: dark person,
        blown window. Their mean lands near the target while the person is
        still a silhouette, so a mean-metered loop declares victory and stops —
        observed on the exhibit, with the loop settling at exposure 117 while
        the visitor was unreadable. A low percentile sits inside the dark mode,
        so the person is what gets exposed and the window is allowed to clip.
        """
        h, w = frame.shape[:2]
        x, y, rw, rh = rect
        cx, cy = x + rw / 2.0, y + rh / 2.0
        rw *= self.cfg.roi_pad
        rh *= self.cfg.roi_pad
        x0 = int(_clamp(cx - rw / 2.0, 0.0, 1.0) * w)
        x1 = int(_clamp(cx + rw / 2.0, 0.0, 1.0) * w)
        y0 = int(_clamp(cy - rh / 2.0, 0.0, 1.0) * h)
        y1 = int(_clamp(cy + rh / 2.0, 0.0, 1.0) * h)
        if x1 - x0 < 2 or y1 - y0 < 2:
            return None
        # Sub-sampled: a stride over the crop is a handful of microseconds, and
        # a percentile over a few thousand pixels is as good an estimate as one
        # over a million.
        crop = frame[y0:y1:4, x0:x1:4]
        if crop.size == 0:
            return None
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        return float(np.percentile(gray, self.cfg.meter_percentile))

    # -- the loop ------------------------------------------------------------

    def update(self, frame, hand_result=None, blob_rect=None, now=None):
        """Measure and, if it is time, nudge the camera one step."""
        if not self.ok or frame is None:
            return
        # Recorded before the rate limiter so the debug line reports what the
        # loop was OFFERED, not just what it did with it. Without this the
        # symptom "roi=none" is ambiguous between "nobody there" and "the
        # detectors are finding somebody and it is not reaching us".
        self._offered = ("hands" if self._hand_rect(hand_result) else
                         "blob" if blob_rect else "nothing")
        now = time.monotonic() if now is None else now
        if now < self._next_t or now < self._hold_until:
            return
        self._next_t = now + self.cfg.interval_s

        rect, source = self._roi(hand_result, blob_rect)
        if rect is None:
            # Nobody to meter. Holding is the point: metering an empty room
            # walks the exposure straight back to the windows.
            self.source = "none"
            return
        raw = self._measure(frame, rect)
        if raw is None:
            return
        # The two ROIs frame different things — a hand box and a whole-body
        # motion box do not have the same brightness — so blending across a
        # switch would chase a step that is not a light change.
        if source != self.source:
            self._smoothed = None
        self.source = source

        # Smooth the MEASUREMENT, not the control. The region itself jitters:
        # the motion blob's box redraws every frame and the hands wander over
        # bright and dark background, so the raw reading jumps even when the
        # light is perfectly steady. A dead zone cannot damp that, because the
        # input is what is moving — on the exhibit this showed as gain sweeping
        # 16 -> 144 -> 16 while nothing about the room had changed.
        self._smoothed = raw if self._smoothed is None else \
            self._smoothed + self.cfg.smooth * (raw - self._smoothed)
        measured = self._smoothed
        self.measured = measured

        if abs(self.cfg.target - measured) <= self.cfg.tolerance:
            return          # dead zone — this is what stops it hunting

        # One damped step per tick, brightness being roughly linear in both
        # exposure time and gain. Exposure is spent first going up because it
        # is the quiet way to buy light, and given back last coming down.
        want = _clamp(self.cfg.target / max(measured, 1.0),
                      1.0 - self.cfg.step, 1.0 + self.cfg.step)
        exposure, gain = self.exposure, self.gain
        if want > 1.0:
            if exposure < self.cfg.exposure_max:
                exposure = _clamp(int(round(exposure * want)),
                                  self.cfg.exposure_min, self.cfg.exposure_max)
            else:
                gain = _clamp(gain + self.cfg.gain_step, 0, self.cfg.gain_max)
        else:
            if gain > 0:
                gain = _clamp(gain - self.cfg.gain_step, 0, self.cfg.gain_max)
            else:
                exposure = _clamp(int(round(exposure * want)),
                                  self.cfg.exposure_min, self.cfg.exposure_max)

        if exposure != self.exposure:
            got = set_control(self.path, _EXPOSURE, exposure)
            self.exposure = self.exposure if got is None else got
        if gain != self.gain:
            got = set_control(self.path, _GAIN, gain)
            self.gain = self.gain if got is None else got
        # A UVC camera takes a few frames to act on a new exposure. Measuring
        # inside that window reads the OLD picture, concludes the step did
        # nothing, and doubles down — the classic way these loops oscillate.
        self._hold_until = now + self.cfg.settle_s

    def report(self, now=None):
        """Print the loop's state, throttled. For HALL_DEBUG=1 tuning.

        Without this the only visible symptom of a bad ROI is "the picture
        looks wrong", which is what cost the first on-exhibit pass: the loop
        was working exactly as written and metering the wrong pixels.
        """
        now = time.monotonic() if now is None else now
        if not self.ok or now < self._report_t:
            return
        self._report_t = now + 2.0
        print("camera AE: roi=%-6s offered=%-7s measured=%s target=%.0f "
              "exposure=%s gain=%s"
              % (self.source, self._offered,
                 "--" if self.measured is None else "%5.1f" % self.measured,
                 self.cfg.target, self.exposure, self.gain), flush=True)

    def to_state(self):
        """Debug-block payload (HALL_DEBUG=1)."""
        return {
            "on": self.ok,
            "roi": self.source,
            "measured": round(self.measured, 1)
            if self.measured is not None else None,
            "target": self.cfg.target,
            "exposure": self.exposure if self.ok else None,
            "gain": self.gain if self.ok else None,
        }
