"""Score preprocessing variants by whether the REAL model finds the hand.

This is a measurement, not a smoke test, and the difference matters. It runs
the exhibit's own detector over frames the exhibit's own camera took, on the
Jetson, and reports detections. Nothing here is synthetic: an earlier session
tuned image processing against an invented scene, passed its own test, and
shipped a picture that was worse, so the rule now is that every frame comes
from the real camera and the criterion is detection rather than how the frame
looks to a human.

    # on the Jetson, kiosk stopped so the camera and the GPU are free
    systemctl --user stop hallkiosk.service
    HALL_INFERENCE=gpu python3 tests/bench_hands.py
    HALL_INFERENCE=gpu python3 tests/bench_hands.py --zoom 2.5   # size, not light

Frames come from ``~/hall-testframes`` (``--dir`` to point elsewhere): a T-pose
sweep of three exposures x four gains with one hand against the window wall and
one against dark wood, which is the hard case and the easy case in the same
picture. They are photographs of a person, so they live outside the repo and
are not committed.

Each frame is judged on its own: the tracker is flushed with black frames
first, so what is measured is ACQUISITION — finding a hand that is not already
being tracked, which is what fails at the exhibit — and not a track inherited
from the previous frame of the same pose.

``--zoom`` re-runs on a centre crop scaled back up. It changes apparent hand
size without touching contrast, so it separates the two candidate causes: if
zoom is what lifts detection and preprocessing is not, the exhibit's problem is
distance and no amount of image processing will fix it.
"""

import argparse
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from detection import detectors  # noqa: E402
from detection.detectors import build_hand_detector  # noqa: E402
from hand_view import HandViewport  # noqa: E402
from preprocess import Preprocessor  # noqa: E402
from rendering.drawing import toMpImage  # noqa: E402

# The variants to score. Keep "off" first: it is the baseline every other row
# has to beat, and a variant that only ties is not worth the milliseconds.
VARIANTS = [
    "off",
    "clahe:2.0:8",
    "clahe:3.0:8",
    "clahe:4.0:8",
    "clahe:3.0:16",
    "clahegray:3.0:8",
    "gamma:1.6",
    "gamma:1.6+clahe:3.0:8",
]

FLUSH_FRAMES = 4     # black frames that drop any existing track
REPEATS = 6          # how many times one frame is offered before giving up
WAIT_S = 0.25        # per-frame budget for the async callback


def load_frames(path):
    files = sorted(f for f in os.listdir(path)
                   if f.lower().endswith((".jpg", ".jpeg", ".png")))
    frames = []
    for name in files:
        img = cv2.imread(os.path.join(path, name))
        if img is None:
            print("skipping unreadable %s" % name)
            continue
        # The app mirrors before inference, so the bench does too.
        frames.append((name, cv2.flip(img, 1)))
    return frames


def zoomed(frame, factor, box=None):
    """Crop scaled back to full size: bigger hand, same contrast.

    ``box`` is (x0, y0, x1, y1) in the MIRRORED frame, for aiming the crop at
    one hand; without it the crop is centred.
    """
    h, w = frame.shape[:2]
    if box is not None:
        x0, y0, x1, y1 = box
        crop = frame[y0:y1, x0:x1]
    elif factor > 1.0:
        cw, ch = int(w / factor), int(h / factor)
        x0, y0 = (w - cw) // 2, (h - ch) // 2
        crop = frame[y0:y0 + ch, x0:x0 + cw]
    else:
        return frame
    if crop.size == 0:
        return frame
    return cv2.resize(crop, (w, h), interpolation=cv2.INTER_LINEAR)


class Feeder:
    """Feeds frames to the async detector and waits for each result."""

    def __init__(self, detector):
        self.detector = detector
        self.t_ms = 0

    def feed(self, frame, viewport=None, ts=None):
        """Push one frame, wait for its result, return the hand landmarks.

        With a viewport, the frame is windowed exactly as `main.py` windows it
        and the answer is remapped back, so what is measured is the shipping
        layer rather than a hand-picked crop.
        """
        detectors.latest_hand_packet = (None, None, None)
        self.t_ms += 33
        shown = frame if viewport is None else viewport.view(frame, self.t_ms)
        self.detector.detect_async(image=toMpImage(frame=shown),
                                   timestamp_ms=self.t_ms)
        deadline = time.monotonic() + WAIT_S
        while time.monotonic() < deadline:
            result, _t, got_ts = detectors.latest_hand_packet
            if result is not None:
                if viewport is not None:
                    result = viewport.remap(result, got_ts)
                    if result is None:
                        return []
                return getattr(result, "hand_landmarks", None) or []
            time.sleep(0.002)
        return []

    def flush(self, shape):
        black = np.zeros(shape, dtype=np.uint8)
        for _ in range(FLUSH_FRAMES):
            self.feed(black)


def score(feeder, frames, pre, zoom, box=None, use_viewport=False,
          repeats=REPEATS):
    """Run every frame through one variant. Returns (rows, ms_per_frame).

    With ``use_viewport`` each frame gets a FRESH `HandViewport`, so what is
    measured is acquisition from cold through the shipping layer: the scan has
    to find the hand by itself, with no help from a crop chosen by hand.
    """
    rows = []
    total_ms = 0.0
    for name, raw in frames:
        img = zoomed(raw, zoom, box)
        t0 = time.monotonic()
        img = pre(img)
        total_ms += (time.monotonic() - t0) * 1000.0
        viewport = HandViewport() if use_viewport else None
        feeder.flush(img.shape)
        best = []
        for _ in range(repeats):
            hands = feeder.feed(img, viewport)
            if len(hands) > len(best):
                best = hands
            if len(best) >= 2:
                break
        # Where each hand landed, so a detection can be attributed to the
        # window side or the wood side rather than just counted.
        spots = []
        for hand in best:
            xs = [lm.x for lm in hand]
            ys = [lm.y for lm in hand]
            spots.append((sum(xs) / len(xs), sum(ys) / len(ys)))
        rows.append((name, len(best), spots))
    return rows, total_ms / max(len(frames), 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.expanduser("~/hall-testframes"))
    ap.add_argument("--zoom", type=float, default=1.0)
    ap.add_argument("--crop", default=None,
                    help="x0,y0,x1,y1 in the MIRRORED frame — aims the zoom "
                         "at one hand instead of the centre")
    ap.add_argument("--viewport", action="store_true",
                    help="run the shipping hand_view layer (scan + lock + "
                         "remap) instead of full-frame inference")
    ap.add_argument("--repeats", type=int, default=REPEATS,
                    help="frames offered per still before giving up; the "
                         "viewport scan needs one per position")
    ap.add_argument("--variants", default=None,
                    help="comma-separated specs, overriding the built-in list")
    args = ap.parse_args()

    if not os.path.isdir(args.dir):
        print("no frame directory %s — this bench needs REAL camera frames, "
              "and deliberately has no synthetic fallback" % args.dir)
        return 2
    frames = load_frames(args.dir)
    if not frames:
        print("no frames in %s" % args.dir)
        return 2
    variants = args.variants.split(",") if args.variants else VARIANTS

    box = tuple(int(v) for v in args.crop.split(",")) if args.crop else None
    print("backend HALL_INFERENCE=%s · %d frames from %s · zoom %.2f · crop %s"
          " · viewport %s"
          % (os.environ.get("HALL_INFERENCE", "mediapipe"), len(frames),
             args.dir, args.zoom, box, "on" if args.viewport else "off"))
    detector = build_hand_detector()
    feeder = Feeder(detector)
    try:
        # One warm-up pass: the first inference of a TensorRT engine pays the
        # load, and counting that as a variant's cost would be a lie.
        feeder.flush(frames[0][1].shape)
        feeder.feed(frames[0][1])

        print("\n%-24s %7s %7s %9s   %s"
              % ("variant", "frames", "hands", "ms/frame", "per-frame hands"))
        results = []
        for spec in variants:
            pre = Preprocessor(spec)
            rows, ms = score(feeder, frames, pre, args.zoom, box,
                             args.viewport, args.repeats)
            hit = sum(1 for _n, c, _s in rows if c > 0)
            hands = sum(c for _n, c, _s in rows)
            detail = "".join(str(c) for _n, c, _s in rows)
            print("%-24s %3d/%-3d %7d %9.2f   %s"
                  % (spec, hit, len(rows), hands, ms, detail))
            results.append((spec, hit, hands, rows))

        # Where the detections landed, for the best variant: the window-side
        # hand is the one that matters and a win built entirely out of the
        # easy hand is not a win.
        best = max(results, key=lambda r: (r[2], r[1]))
        print("\nlandmark centres for %r (x,y normalized, x<0.5 = wood side "
              "after mirroring):" % best[0])
        for name, count, spots in best[3]:
            where = " ".join("(%.2f,%.2f)" % s for s in spots) or "-"
            print("  %-14s %d  %s" % (name[:-4], count, where))
    finally:
        detector.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
