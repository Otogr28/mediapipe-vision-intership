"""Smoke test for the subject-metered exposure loop (src/auto_exposure.py).

Runs the controller against a FAKE camera whose picture brightens and darkens
the way a real one does, so the things that actually go wrong in a control loop
are what get pinned: does it converge, does it hunt, does it hold when nobody
is there, does it stop before the shutter is long enough to smear a hand.

Like the rest of `tests/`, this is a plain `python` script — no pytest — so it
runs on the Jetson's system 3.10 as well as the laptop's 3.12.
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

import auto_exposure  # noqa: E402
from auto_exposure import SubjectExposure  # noqa: E402
from config import _AutoExposureConfig  # noqa: E402

FAIL = []

# How much light the "backlit visitor" scene puts on the sensor. It has to be
# dark enough that the loop starts well under the target (0.15 * the camera's
# default 156 = luminance 23, a silhouette) but bright enough that the target
# is REACHABLE within the exposure and gain ceilings — 0.15 * 250 * 4.125 =
# 154, comfortably past 120. Pick an unreachable scene and the test is asking
# the controller to break its own blur ceiling; `check_shutter_ceiling` covers
# that case deliberately, with a scene nothing can rescue.
DARK_SCENE = 0.15


def check(name, ok, detail=""):
    print("%-52s %s%s" % (name, "OK" if ok else "FAIL",
                          "" if ok else "  <- " + detail))
    if not ok:
        FAIL.append(name)


class FakeCamera:
    """A camera whose brightness is linear in exposure*gain, with a ceiling.

    `scene` is how much light reaches the sensor: a small number is the backlit
    visitor this whole module exists for.
    """

    def __init__(self, scene=0.06):
        self.scene = scene
        self.values = {auto_exposure._AUTO_EXPOSURE: 3,
                       auto_exposure._EXPOSURE: 156,
                       auto_exposure._GAIN: 0}
        self.writes = 0

    def get(self, _path, cid):
        return self.values.get(cid)

    def set(self, _path, cid, value):
        self.values[cid] = int(value)
        self.writes += 1
        return self.values[cid]

    def _lum(self):
        return self.scene * self.values[auto_exposure._EXPOSURE] \
            * (1.0 + self.values[auto_exposure._GAIN] / 64.0)

    def frame(self, w=320, h=180):
        return np.full((h, w, 3), min(255, max(0, int(self._lum()))),
                       dtype=np.uint8)

    def backlit_frame(self, w=320, h=180, subject_frac=0.5, jitter=0):
        """The real scene: a dark subject beside a blown-out window.

        `subject_frac` is how much of the metered box the person fills, and
        `jitter` shifts that boundary each call — which is what a redrawn
        motion box or a wandering hand does to the reading in the hall.
        """
        frame = np.full((h, w, 3), 255, dtype=np.uint8)     # window: clipped
        cut = int(w * subject_frac) + jitter
        frame[:, :max(0, min(w, cut))] = min(255, max(0, int(self._lum())))
        return frame


def install(cam):
    auto_exposure.get_control = cam.get
    auto_exposure.set_control = cam.set


def run(ctrl, cam, ticks, rect=(0.3, 0.3, 0.4, 0.4), t0=0.0, dt=0.5):
    """Drive the loop `ticks` times, returning the luminance trace."""
    trace = []
    t = t0
    for _ in range(ticks):
        t += dt
        ctrl.update(cam.frame(), None, rect, now=t)
        trace.append(cam.frame()[0, 0, 0])
    return trace


def check_converges():
    cam = FakeCamera(scene=DARK_SCENE)      # dark: the backlit silhouette
    install(cam)
    cfg = _AutoExposureConfig()
    ctrl = SubjectExposure("/dev/null", cfg)
    trace = run(ctrl, cam, 40)
    final = trace[-1]
    check("dark subject converges to the target",
          abs(final - cfg.target) <= cfg.tolerance + 2,
          "ended at %s, target %s" % (final, cfg.target))

    cam2 = FakeCamera(scene=3.0)      # blown out
    install(cam2)
    ctrl2 = SubjectExposure("/dev/null", cfg)
    trace2 = run(ctrl2, cam2, 40)
    check("blown-out subject converges to the target",
          abs(trace2[-1] - cfg.target) <= cfg.tolerance + 2,
          "ended at %s" % trace2[-1])


def check_settles():
    """The dead zone has to actually stop the loop, or the picture breathes."""
    cam = FakeCamera(scene=DARK_SCENE)
    install(cam)
    cfg = _AutoExposureConfig()
    ctrl = SubjectExposure("/dev/null", cfg)
    run(ctrl, cam, 40)
    writes_before = cam.writes
    run(ctrl, cam, 20, t0=100.0)
    check("no writes once inside the dead zone",
          cam.writes == writes_before,
          "%d extra writes" % (cam.writes - writes_before))


def check_no_oscillation():
    """A settled loop must not swing across the target frame after frame."""
    cam = FakeCamera(scene=DARK_SCENE)
    install(cam)
    cfg = _AutoExposureConfig()
    ctrl = SubjectExposure("/dev/null", cfg)
    trace = run(ctrl, cam, 60)
    tail = trace[-15:]
    check("settled luminance is stable (spread <= tolerance)",
          max(tail) - min(tail) <= cfg.tolerance,
          "spread %d over %s" % (max(tail) - min(tail), tail))


def check_holds_without_subject():
    """Nobody in frame means hold — metering an empty room re-exposes the
    windows and undoes everything the loop achieved."""
    cam = FakeCamera(scene=DARK_SCENE)
    install(cam)
    cfg = _AutoExposureConfig()
    ctrl = SubjectExposure("/dev/null", cfg)
    run(ctrl, cam, 40)
    settled = (cam.values[auto_exposure._EXPOSURE],
               cam.values[auto_exposure._GAIN])
    t = 100.0
    for _ in range(20):
        t += 0.5
        ctrl.update(cam.frame(), None, None, now=t)   # no hands, no blob
    now = (cam.values[auto_exposure._EXPOSURE],
           cam.values[auto_exposure._GAIN])
    check("holds exposure when there is no subject", now == settled,
          "%s -> %s" % (settled, now))


def check_shutter_ceiling():
    """Exposure must stop at the motion-blur ceiling and buy the rest with
    gain: a smeared hand is not trackable, however well exposed it is."""
    cam = FakeCamera(scene=0.002)     # so dark only gain can finish the job
    install(cam)
    cfg = _AutoExposureConfig()
    ctrl = SubjectExposure("/dev/null", cfg)
    run(ctrl, cam, 60)
    exposure = cam.values[auto_exposure._EXPOSURE]
    gain = cam.values[auto_exposure._GAIN]
    check("exposure never exceeds the blur ceiling",
          exposure <= cfg.exposure_max,
          "exposure %d > %d" % (exposure, cfg.exposure_max))
    check("gain takes over once exposure is capped", gain > 0,
          "gain still %d" % gain)
    check("gain never exceeds its cap", gain <= cfg.gain_max,
          "gain %d > %d" % (gain, cfg.gain_max))


def check_hand_roi_wins():
    """Hands are the finer target and must outrank the motion blob."""
    cam = FakeCamera(scene=DARK_SCENE)
    install(cam)
    ctrl = SubjectExposure("/dev/null", _AutoExposureConfig())

    class Hand:
        def __init__(self, x, y):
            self.x, self.y = x, y

    class Result:
        hand_landmarks = [[Hand(0.5, 0.5), Hand(0.6, 0.7)]]

    ctrl.update(cam.frame(), Result(), (0.0, 0.0, 1.0, 1.0), now=1.0)
    check("hands outrank the motion blob as the ROI",
          ctrl.source == "hands", "source was %r" % ctrl.source)
    ctrl2 = SubjectExposure("/dev/null", _AutoExposureConfig())
    ctrl2.update(cam.frame(), None, (0.2, 0.2, 0.5, 0.5), now=1.0)
    check("motion blob is used when there are no hands",
          ctrl2.source == "motion", "source was %r" % ctrl2.source)


def check_backlit_subject():
    """THE case this module exists for, and the one the exhibit failed.

    Half the metered box is a clipped window. Metering its MEAN reads ~140
    while the person is still near black, so a mean-metered loop stops — that
    is exactly what happened in the hall (settled at exposure 117, visitor
    unreadable). The subject itself has to reach the target.
    """
    cam = FakeCamera(scene=DARK_SCENE)
    install(cam)
    cfg = _AutoExposureConfig()
    ctrl = SubjectExposure("/dev/null", cfg)
    t = 0.0
    for _ in range(50):
        t += 0.5
        ctrl.update(cam.backlit_frame(), None, (0.0, 0.0, 1.0, 1.0), now=t)
    subject = cam.backlit_frame()[0, 0, 0]
    check("backlit subject itself reaches the target",
          abs(int(subject) - cfg.target) <= cfg.tolerance + 4,
          "subject luminance %s, target %s" % (subject, cfg.target))


# How much of the metered box the subject fills, tick by tick. The motion box
# is redrawn every frame around whatever moved, so from one tick to the next it
# genuinely frames different amounts of person and window. At 0.30 the metering
# percentile falls in the WINDOW and the reading leaps to white; at 0.55 and
# 0.70 it is back on the person. That leap is the input that made gain sweep
# 16 -> 144 -> 16 on the exhibit while the light never changed.
_ROI_WOBBLE = (0.55, 0.30, 0.70, 0.55, 0.30, 0.65)


def check_jittery_roi():
    """A moving ROI must not move the exposure. Smoothing the measurement is
    the only thing that can absorb it — a dead zone cannot, because it is the
    INPUT that is jumping, not the output."""
    cam = FakeCamera(scene=DARK_SCENE)
    install(cam)
    cfg = _AutoExposureConfig()
    ctrl = SubjectExposure("/dev/null", cfg)
    t = 0.0
    for i in range(60):                       # settle with a wobbling box
        t += 0.5
        ctrl.update(cam.backlit_frame(subject_frac=_ROI_WOBBLE[i % 6]), None,
                    (0.0, 0.0, 1.0, 1.0), now=t)
    lum = []
    for i in range(36):                       # then watch it hold
        t += 0.5
        ctrl.update(cam.backlit_frame(subject_frac=_ROI_WOBBLE[i % 6]), None,
                    (0.0, 0.0, 1.0, 1.0), now=t)
        lum.append(int(cam._lum()))
    # Assert on the SUBJECT, not on the controls: a loop can hold its gain
    # perfectly steady and still be holding the person at black, which is what
    # the earlier version of this test missed. Metering percentile 40 leaves
    # the subject at 56-65 here and no smoothing leaves it near 24; both pass a
    # control-stability assertion and both are the failure.
    check("a wobbling ROI still lands the subject on target",
          abs(min(lum) - cfg.target) <= cfg.tolerance + 4
          and abs(max(lum) - cfg.target) <= cfg.tolerance + 4,
          "subject luminance %d..%d, target %d"
          % (min(lum), max(lum), cfg.target))


def check_manual_mode_required():
    """In any automatic mode the camera owns exposure and drops our writes, so
    the controller must refuse to run rather than pretend it is working."""
    cam = FakeCamera()
    cam.set = lambda _p, cid, v: 3 if cid == auto_exposure._AUTO_EXPOSURE \
        else v
    install(cam)
    ctrl = SubjectExposure("/dev/null", _AutoExposureConfig())
    check("disables itself when manual mode is refused", not ctrl.ok)


def main():
    print("=== subject-metered exposure ===")
    check_converges()
    check_settles()
    check_no_oscillation()
    check_holds_without_subject()
    check_shutter_ceiling()
    check_hand_roi_wins()
    check_backlit_subject()
    check_jittery_roi()
    check_manual_mode_required()
    print()
    if FAIL:
        print("FAILED: %s" % ", ".join(FAIL))
        return 1
    print("all exposure checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
