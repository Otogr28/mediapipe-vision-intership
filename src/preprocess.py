"""A layer between the camera frame and the model, for the backlit hand.

The exhibit camera looks down a corridor at a wall of windows and cannot be
moved or re-aimed. A visitor's hand held up against that glass is the hard case
of the whole application, and the shape of the problem is NOT what "backlit"
suggests. Measured on the exhibit's own frames (`~/hall-testframes` on the
Jetson, a T-pose sweep of three exposures x four gains):

    frame       palm vs window   contrast
    e160-g0        207 / 232         25
    e100-g0        180 / 215         35
    e60-g64        155 / 206         51
    e100-g64       132 / 191         59

The hand is not dark. It sits around 130-200 of 255 against a window already
clipping at 255, flattened further by veiling glare, and the ONLY thing that
tracks with hand legibility is the gap between the two. More light closes that
gap: every extra stop lifts the hand toward the clipped white it has to be
distinguished from, and at exposure 160 the fingers stop separating from the
glass at all. **Brightness is the wrong axis. Contrast is the axis.** Anything
proposed here that makes the picture brighter has already been tried and made
the model worse, twice.

So this module does not touch exposure. It reshapes the pixels on their way to
the detector, and only on that path: `main.py` keeps the untouched frame for
the sink, so what the visitor sees behind the scenes is the camera picture and
what the model sees is a version with the hand pulled off the window.

The default is CLAHE on the lightness channel. Contrast-limited adaptive
histogram equalization equalizes per tile, so the tile holding hand-plus-window
gets its local range stretched (that is exactly the 130-vs-255 case) while the
tile holding the other hand against dark wood is left near where it was. A
global curve cannot do both, and this exhibit needs both in the same frame.

Everything is off unless `HALL_PREPROCESS` asks for it, so a laptop webcam and
every smoke script see the frame the camera produced.

The spec is a small composable string, chained with `+`, so the bench that
measures a variant and the app that ships it run the SAME code:

    clahe              CLAHE on L (LAB), default clip and tiles
    clahe:3.0:8        ... with clip limit 3.0 and an 8x8 tile grid
    clahegray:3.0:8    CLAHE on grey, replicated to three channels
    gamma:1.6          LUT gamma (>1 darkens midtones and expands highlights)
    gamma:1.4+clahe:3  chained, applied left to right
"""

import cv2
import numpy as np

# Reused across frames: building a CLAHE object per frame allocates its
# histogram tables every time, which is pure overhead at 30 fps.
_clahe_cache = {}
_gamma_cache = {}


def _clahe(clip, tiles):
    key = (round(float(clip), 3), int(tiles))
    if key not in _clahe_cache:
        _clahe_cache[key] = cv2.createCLAHE(clipLimit=key[0],
                                            tileGridSize=(key[1], key[1]))
    return _clahe_cache[key]


def _gamma_lut(g):
    key = round(float(g), 3)
    if key not in _gamma_cache:
        x = np.arange(256, dtype=np.float32) / 255.0
        _gamma_cache[key] = np.clip(np.power(x, key) * 255.0,
                                    0, 255).astype(np.uint8)
    return _gamma_cache[key]


def _op_clahe(frame, clip=3.0, tiles=8):
    """CLAHE on lightness, colour untouched.

    LAB rather than grey because the hand against the window keeps a chroma
    difference the luminance has almost lost, and the palm detector was trained
    on colour images.
    """
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    lab[:, :, 0] = _clahe(clip, tiles).apply(lab[:, :, 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def _op_clahegray(frame, clip=3.0, tiles=8):
    """CLAHE on grey, replicated to three channels.

    Throws the colour cast away with the colour. Worth measuring rather than
    reasoning about: the hall's window light is strongly cyan and the model
    may do better without it than with it.
    """
    grey = _clahe(clip, tiles).apply(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
    return cv2.cvtColor(grey, cv2.COLOR_GRAY2BGR)


def _op_gamma(frame, g=1.6):
    """Global tone curve. ``g`` > 1 darkens midtones and expands highlights.

    The cheap, dumb version of the idea: it does buy separation up where the
    hand and the window are, at the price of everything below. Kept because it
    costs one LUT and the measurement should include a naive baseline.
    """
    return cv2.LUT(frame, _gamma_lut(g))


_OPS = {
    "clahe": _op_clahe,
    "clahegray": _op_clahegray,
    "gamma": _op_gamma,
}


def parse(spec):
    """Compile a spec string into a list of (callable, args), or []."""
    spec = (spec or "").strip().lower()
    if not spec or spec in ("off", "none", "0"):
        return []
    steps = []
    for part in spec.split("+"):
        bits = [b for b in part.strip().split(":") if b != ""]
        if not bits:
            continue
        name = bits[0]
        if name not in _OPS:
            raise ValueError("unknown preprocess op %r (have: %s)"
                             % (name, ", ".join(sorted(_OPS))))
        steps.append((_OPS[name], [float(b) for b in bits[1:]]))
    return steps


class Preprocessor:
    """Applies a compiled spec to the frame handed to the detectors.

    Never mutates its input: the caller keeps the original for the sink, and
    an in-place filter would put the enhancement on screen as well.
    """

    def __init__(self, spec):
        self.spec = (spec or "off").strip() or "off"
        self.steps = parse(spec)
        self.enabled = bool(self.steps)

    def __call__(self, frame):
        if not self.enabled or frame is None:
            return frame
        out = frame
        for op, args in self.steps:
            out = op(out, *args)
        return out

    def describe(self):
        return self.spec if self.enabled else "off"
