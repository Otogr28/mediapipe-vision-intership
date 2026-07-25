"""High-level gestures derived from raw MediaPipe landmarks.

Two closing gestures share one state machine, selected by ``HALL_GESTURE``
(``config.GESTURE_MODE``): the thumb-index **pinch** and the whole-hand
**fist**. ``"either"`` (the default) closes on whichever the visitor makes.
Both are reduced to a single ``ratio`` in the pinch's units before the
machine sees them, so the hysteresis, debounce, ``progress`` and every
downstream consumer are identical whichever gesture fired — see
``_combined_ratio``.

The pipeline is built from the techniques production hand-tracking stacks use:

* **Per-frame snapshot.** ``update_pinches()`` advances one state machine per
  hand exactly once per rendered frame; every consumer (buttons, spheres,
  experiments) then reads the same snapshot through ``pinch_state()`` /
  ``pinch_info()``. The previous design mutated a shared ratio history on
  *every* read, so each extra widget on screen shrank the detector's time
  window and made pinching progressively harder.
* **Edge-triggered state machine with hysteresis** (Ultraleap's pinch/unpinch
  split): the machine closes below ``PINCH_CLOSE_RATIO`` and only reopens
  above the looser ``PINCH_RELEASE_RATIO``, so jitter at the threshold cannot
  flicker the state. The ``pinching`` event fires exactly once, on the
  open->closed transition — a hand that enters the frame already closed
  starts silently in the closed state and never fires (a fist sliding over a
  button still cannot click it).
* **Debounce** — the state flips only after a few consecutive agreeing
  frames (``PINCH_DEBOUNCE_*``), because tracking gives brief false
  negatives exactly while the user pinches and moves at the same time.
* **One-Euro filtering** (Casiez, Roussel & Vogel, CHI 2012) on both the
  pinch ratio and the cursor: heavy smoothing at rest kills the jitter,
  light smoothing during fast motion keeps latency invisible.
* **Fist = finger curl, measured as a ratio of two wrist distances**:
  ``|tip - wrist| / |MCP - wrist|`` per finger, averaged over index, middle,
  ring and pinky. Both distances foreshorten together when the hand tilts
  toward the camera, so unlike a raw finger length the metric survives hand
  orientation, and it needs no size reference at all. The thumb is left out:
  it folds ACROSS the palm rather than into it, so its own ratio barely
  moves between an open hand and a fist. Thresholds in ``config``
  (``FIST_CLOSE_RATIO`` / ``FIST_RELEASE_RATIO``).
* **Thumb-anchored cursor** (``HALL_GESTURE=pinch`` only): the cursor rides
  the THUMB TIP (landmark 4).
  In a thumb-index pinch the index does most of the closing travel while
  the thumb stays comparatively still, so anchoring on the thumb keeps the
  dot on the finger the user aims with and nearly motionless through the
  close. ``PINCH_CURSOR_THUMB_OFFSET_X`` / ``_Y`` optionally offset it in
  the thumb's own frame — X along the thumb ray (MCP 2 -> tip 4), Y
  perpendicular to it (positive toward the index side, sign resolved per
  hand so Left/Right mirror correctly) — both as fractions of that
  segment, hand-scaled and rotation-following; 0/0 = at the tip.
  ``PINCH_CURSOR_COMPENSATE`` (0..1) adds a close COUNTER-MOVEMENT: the
  cursor's open-pose coordinates in a rigid hand frame (wrist -> index
  MCP) are remembered and, as the pinch progresses, the cursor is pulled
  back toward that remembered point — cancelling the thumb's own close
  travel while still following real hand motion. ``press_cursor``
  (latched where the close started) additionally guards button clicks.
  Both fingertips (4, 8) still drive the pinch *ratio*.
* **Latency compensation**: the cursor is extrapolated forward by its
  One-Euro velocity times the detection result's age (``received_t`` from
  the detector callback), capped at ``PINCH_EXTRAP_MAX_S``. Linear velocity
  extrapolation — at short horizons it beats Kalman on jitter. Only the
  *output* is extrapolated, never the filter state.
* **3D pinch distance**: the landmark ``z`` difference (wrist-relative,
  ~x-normalized units) joins the tip distance weighted by
  ``PINCH_Z_WEIGHT`` — so rotating the hand until the tips visually overlap
  no longer fakes a close. ``z`` missing/zero degrades to pure 2D.
* **Hand-relative scale.** Distances are normalized by the hand's own size
  (knuckle span / palm length — segments that do not move when the fingers
  close), so the thresholds hold at any camera distance, a fist cannot
  collapse the reference, and — unlike a shoulder-width scale — the pinch
  keeps working when the pose/shoulders are not visible.
"""

import math
import time

from config import (FIST_CLOSE_RATIO, FIST_CURSOR_LANDMARK, FIST_RELEASE_RATIO,
                    GESTURE_MODE, PINCH_CLOSE_RATIO, PINCH_CURSOR_BETA,
                    PINCH_CURSOR_COMPENSATE, PINCH_CURSOR_MIN_CUTOFF,
                    PINCH_CURSOR_THUMB_OFFSET_X, PINCH_CURSOR_THUMB_OFFSET_Y,
                    PINCH_DEBOUNCE_CLOSE_FRAMES, PINCH_DEBOUNCE_RELEASE_FRAMES,
                    PINCH_EXTRAP_MAX_S, PINCH_RATIO_BETA,
                    PINCH_RATIO_MIN_CUTOFF, PINCH_RELEASE_RATIO,
                    PINCH_TRACK_GRACE_S, PINCH_Z_WEIGHT)

PINCH_LANDMARK_A = 4   # thumb tip (hand) — the cursor anchor in "pinch" mode
PINCH_LANDMARK_B = 8   # index finger tip (hand)

THUMB_MCP = 2          # base of the thumb ray for the cursor offset

WRIST = 0
# (tip, MCP) per finger for the curl ratio. The thumb (4, 2) is deliberately
# absent — it folds across the palm, not into it, so its ratio hardly moves.
CURL_FINGERS = ((8, 5), (12, 9), (16, 13), (20, 17))

# Only the thumb-index pinch justifies the thumb-tip anchor and its
# counter-movement compensation: they exist to cancel the travel of the ONE
# finger that closes. When the whole hand closes there is no such finger, so
# the cursor sits on the palm knuckle instead (a point the fingers cannot move).
USE_THUMB_ANCHOR = GESTURE_MODE == "pinch"

HAND_SCALE_KNUCKLE_A = 5     # index finger MCP (knuckle)
HAND_SCALE_KNUCKLE_B = 17    # pinky MCP (knuckle)
HAND_SCALE_PALM_A = 0        # wrist
HAND_SCALE_PALM_B = 9        # middle finger MCP
HAND_SCALE_PALM_FACTOR = 0.75  # palm length -> knuckle-span equivalent

POSE_SCALE_A = 11      # left shoulder (pose)
POSE_SCALE_B = 12      # right shoulder (pose)
POSE_SCALE_MIN_VISIBILITY = 0.5


def hand_id(hand_result, i):
    """Best-effort stable id for the i-th hand in a HandLandmarkerResult.

    Prefers MediaPipe's handedness category ("Left" / "Right") since the
    iteration index can swap between frames. Falls back to the index when
    handedness is unavailable.
    """
    if hand_result and hand_result.handedness and i < len(hand_result.handedness):
        cats = hand_result.handedness[i]
        if cats:
            return cats[0].category_name
    return f"hand_{i}"


def pose_scale(pose_landmarks, frame_w, frame_h):
    """Shoulder-to-shoulder pixel distance from the pose landmarks.

    A depth-invariant size proxy for *pose-relative* gestures (arm raises,
    body-scaled distances). The pinch no longer uses it — see
    ``hand_scale`` — but it remains the reference for any future gesture
    measured against the body rather than the hand.

    Returns ``0.0`` when either shoulder is missing or below the
    visibility threshold, which callers should treat as "no scale
    available — skip gesture detection".
    """
    if not pose_landmarks:
        return 0.0

    a = pose_landmarks[POSE_SCALE_A]
    b = pose_landmarks[POSE_SCALE_B]

    if a.visibility is not None and a.visibility < POSE_SCALE_MIN_VISIBILITY:
        return 0.0
    if b.visibility is not None and b.visibility < POSE_SCALE_MIN_VISIBILITY:
        return 0.0

    ax, ay = a.x * frame_w, a.y * frame_h
    bx, by = b.x * frame_w, b.y * frame_h
    return math.hypot(ax - bx, ay - by)


def hand_scale(hand_landmarks, frame_w, frame_h):
    """Pixel-size proxy of one hand, from segments that fingers can't move.

    ``max`` of the knuckle span (index MCP -> pinky MCP) and a scaled palm
    length (wrist -> middle MCP): both are rigid under finger motion, so a
    closing fist cannot collapse the reference, and taking the larger one
    keeps the scale usable when hand rotation foreshortens either segment.
    Deliberately 2D — z is too noisy for the *denominator* of every ratio.
    """
    a = hand_landmarks[HAND_SCALE_KNUCKLE_A]
    b = hand_landmarks[HAND_SCALE_KNUCKLE_B]
    knuckle = math.hypot((a.x - b.x) * frame_w, (a.y - b.y) * frame_h)
    c = hand_landmarks[HAND_SCALE_PALM_A]
    d = hand_landmarks[HAND_SCALE_PALM_B]
    palm = math.hypot((c.x - d.x) * frame_w, (c.y - d.y) * frame_h)
    return max(knuckle, palm * HAND_SCALE_PALM_FACTOR)


def _dist3(a, b, frame_w, frame_h):
    """Landmark distance in pixels, with ``z`` mixed in at ``PINCH_Z_WEIGHT``.

    ``z`` is wrist-relative in ~x-normalized units, so ``frame_w`` puts it in
    the same pixels as dx/dy; a backend that omits it degrades to pure 2D.
    """
    dx = (a.x - b.x) * frame_w
    dy = (a.y - b.y) * frame_h
    dz = (getattr(a, "z", 0.0) - getattr(b, "z", 0.0)) * frame_w * PINCH_Z_WEIGHT
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def pinch_ratio(hand_landmarks, frame_w, frame_h, scale):
    """Thumb-index tip distance over the hand's own size (see ``hand_scale``).

    Falls below ``PINCH_CLOSE_RATIO`` as the two fingertips meet.
    """
    return _dist3(hand_landmarks[PINCH_LANDMARK_A],
                  hand_landmarks[PINCH_LANDMARK_B], frame_w, frame_h) / scale


def fist_ratio(hand_landmarks, frame_w, frame_h):
    """How OPEN the hand is: mean of ``|tip - wrist| / |MCP - wrist|`` over
    index, middle, ring and pinky.

    ~1.85 with the fingers straight out, ~1.6 relaxed, ~0.7 in a deliberate
    fist, on any hand at any camera distance — both distances share the same
    wrist origin, so hand size cancels and foreshortening affects numerator
    and denominator together. A fist reads well below 1 because each tip
    folds back PAST its own knuckle, which is what separates it cleanly from
    every half-curled pose. Returns ``None`` if the knuckles are degenerate
    (a hand seen edge-on can collapse |MCP - wrist| to nothing), which the
    caller treats as "no fist reading this frame" rather than a closed hand.
    """
    wrist = hand_landmarks[WRIST]
    total = 0.0
    for tip_i, mcp_i in CURL_FINGERS:
        base = _dist3(hand_landmarks[mcp_i], wrist, frame_w, frame_h)
        if base <= 1e-6:
            return None
        total += _dist3(hand_landmarks[tip_i], wrist, frame_w, frame_h) / base
    return total / len(CURL_FINGERS)


# The fist's open/closed band mapped onto the pinch's, so ONE ratio in pinch
# units drives the state machine whichever gesture produced it. Everything
# downstream — hysteresis, debounce, `progress`, the debug HUD's thresholds —
# then needs no idea which gesture is configured.
_FIST_TO_PINCH_GAIN = ((PINCH_RELEASE_RATIO - PINCH_CLOSE_RATIO)
                       / (FIST_RELEASE_RATIO - FIST_CLOSE_RATIO))


def _fist_in_pinch_units(ratio):
    # Floored at 0: a firm fist sits far below FIST_CLOSE_RATIO and would map
    # to a negative ratio. The machine would not care (it only asks whether
    # the ratio is under the close threshold) but the debug HUD draws a bar
    # of width ratio/1.5, and the state payload documents `ratio` as a
    # distance-like quantity. Keep it well-formed at the source.
    return max(0.0, PINCH_CLOSE_RATIO
               + (ratio - FIST_CLOSE_RATIO) * _FIST_TO_PINCH_GAIN)


def _combined_ratio(pinch_r, fist_r):
    """The single ratio the state machine runs on, per ``GESTURE_MODE``.

    In ``"either"`` mode the two gestures are combined with ``min`` — the
    hand counts as closed as soon as EITHER reading says so — after each has
    been filtered separately. Filtering first matters: ``min`` of two noisy
    signals is biased toward whichever happens to be low this frame, so
    combining raw readings would drift the trigger point downward.
    """
    if GESTURE_MODE == "pinch":
        return pinch_r
    fist_r = None if fist_r is None else _fist_in_pinch_units(fist_r)
    if GESTURE_MODE == "fist":
        return fist_r
    if fist_r is None:
        return pinch_r
    return min(pinch_r, fist_r)


class _OneEuroFilter:
    """One-Euro filter (Casiez, Roussel & Vogel, CHI 2012).

    An adaptive low-pass: the cutoff frequency grows with the signal's
    speed, so slow signals are smoothed hard (no jitter) while fast motion
    passes through nearly unfiltered (no perceptible lag).
    """

    def __init__(self, min_cutoff, beta, d_cutoff=1.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self._x_prev = None
        self._dx_prev = 0.0

    @property
    def velocity(self):
        """Smoothed signal derivative (units/s) — already low-passed at
        ``d_cutoff``, which is what makes it safe for extrapolation."""
        return self._dx_prev

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, x, dt):
        if self._x_prev is None:
            self._x_prev = x
            return x
        a_d = self._alpha(self.d_cutoff, dt)
        dx = (x - self._x_prev) / dt
        dx_hat = a_d * dx + (1.0 - a_d) * self._dx_prev
        cutoff = self.min_cutoff + self.beta * abs(dx_hat)
        a = self._alpha(cutoff, dt)
        x_hat = a * x + (1.0 - a) * self._x_prev
        self._x_prev = x_hat
        self._dx_prev = dx_hat
        return x_hat


class _HandPinch:
    """Pinch state machine + filters for a single tracked hand.

    Instances are handed out read-only via ``pinch_info`` / ``pinch_infos``;
    all mutation happens inside ``advance()``, which ``update_pinches``
    calls exactly once per rendered frame.
    """

    def __init__(self):
        self.closed = False
        self.pinching = False        # edge event: True for one frame only
        self.cursor = (0.0, 0.0)
        # Filtered readings of each gesture in its OWN units, for the debug
        # HUD (`ratio` below is the combined, pinch-unit signal the machine
        # actually runs on). `fist_ratio` is None on a frame whose knuckles
        # were too degenerate to measure curl.
        self.pinch_ratio = None
        self.fist_ratio = None
        # Cursor latched where the close gesture STARTED (close debounce
        # 0->1); consumers hit-test clicks against this so the hand drifting
        # during the close cannot slide the click off its target.
        self.press_cursor = (0.0, 0.0)
        # The combined ratio the machine runs on, always in PINCH units
        # whichever gesture produced it (None until the hand is first seen).
        self.ratio = None
        self.last_seen = 0.0
        # Open-pose cursor coordinates in the rigid hand frame (wrist ->
        # index MCP basis) — the anchor of the close counter-movement.
        self._cursor_ref = None
        self._initialised = False
        self._close_frames = 0
        self._open_frames = 0
        self._fx = _OneEuroFilter(PINCH_CURSOR_MIN_CUTOFF, PINCH_CURSOR_BETA)
        self._fy = _OneEuroFilter(PINCH_CURSOR_MIN_CUTOFF, PINCH_CURSOR_BETA)
        self._fr = _OneEuroFilter(PINCH_RATIO_MIN_CUTOFF, PINCH_RATIO_BETA)
        # The fist reading shares the pinch ratio's filter tuning: its
        # open->closed band (1.45 -> 1.05) spans about as much as the pinch's
        # (0.90 -> 0.45), so the same beta reacts at the same rate per unit
        # of gesture travel.
        self._ff = _OneEuroFilter(PINCH_RATIO_MIN_CUTOFF, PINCH_RATIO_BETA)

    @property
    def progress(self):
        """Continuous pinch strength 0..1 (Meta-style): 0 at/above the
        release threshold, 1 at/below the close threshold."""
        if self.ratio is None:
            return 0.0
        span = PINCH_RELEASE_RATIO - PINCH_CLOSE_RATIO
        return min(max((PINCH_RELEASE_RATIO - self.ratio) / span, 0.0), 1.0)

    @property
    def state(self):
        """One of "open" / "closing" / "closed" / "releasing"."""
        if self.closed:
            return "releasing" if self._open_frames > 0 else "closed"
        return "closing" if self._close_frames > 0 else "open"

    def advance(self, hand_landmarks, frame_w, frame_h, dt, now, age_s):
        a = hand_landmarks[PINCH_LANDMARK_A]
        ax, ay = a.x * frame_w, a.y * frame_h

        scale = hand_scale(hand_landmarks, frame_w, frame_h)
        if scale <= 0.0:
            # Degenerate landmarks; keep the previous state, fire nothing.
            self.pinching = False
            self.last_seen = now
            return

        # Measure and filter BOTH gestures every frame, whichever is
        # configured: the spare one costs four landmark distances and it is
        # what makes HALL_GESTURE tunable against a live hand through the
        # debug HUD. `_combined_ratio` then reduces them to the single
        # pinch-unit signal the state machine below runs on.
        self.pinch_ratio = self._fr(
            pinch_ratio(hand_landmarks, frame_w, frame_h, scale), dt)
        raw_fist = fist_ratio(hand_landmarks, frame_w, frame_h)
        self.fist_ratio = (self._ff(raw_fist, dt)
                           if raw_fist is not None else None)
        self.ratio = _combined_ratio(self.pinch_ratio, self.fist_ratio)
        if self.ratio is None:
            # "fist" mode on a frame whose curl could not be measured (a hand
            # seen edge-on collapses |MCP - wrist|). Hold the previous state
            # rather than inventing a closure out of a missing reading.
            self.pinching = False
            self.last_seen = now
            return

        if not USE_THUMB_ANCHOR:
            # Fist/either: the cursor sits on the palm knuckle (landmark 9).
            # The fingers cannot move it, so a closing hand does not drag the
            # cursor and none of the thumb machinery below is needed — this
            # is also the point a visitor reads as "where my hand is" when
            # they aim a closed hand at a button.
            palm = hand_landmarks[FIST_CURSOR_LANDMARK]
            raw_x, raw_y = palm.x * frame_w, palm.y * frame_h
            self._advance_cursor(raw_x, raw_y, dt, age_s)
            self._advance_machine(now)
            return

        # Cursor: anchored to the THUMB TIP (landmark 4, already in ax/ay),
        # optionally offset in the thumb's own frame: X slides along the
        # thumb ray (MCP 2 -> tip 4), Y perpendicular to it — both as
        # fractions of that segment, so the offset is hand-scaled and
        # rotation-following (it means the same thing at any distance or
        # orientation). The perpendicular's sign is resolved against the
        # index MCP so +Y always points toward the index side of the
        # thumb, on either hand. The thumb is the stable side of a
        # thumb-index pinch — the index does most of the closing travel —
        # so the dot tracks the finger the user aims with and barely moves
        # through the close; buttons additionally hit-test the
        # press-latched cursor, so the residual thumb travel cannot slide
        # a click off its target. Filter it, then extrapolate the OUTPUT
        # forward by the filter's velocity times the detection age (never
        # feed the extrapolation back into the filter, or the correction
        # compounds).
        raw_x, raw_y = ax, ay
        if PINCH_CURSOR_THUMB_OFFSET_X or PINCH_CURSOR_THUMB_OFFSET_Y:
            tm = hand_landmarks[THUMB_MCP]
            rx = (a.x - tm.x) * frame_w   # thumb ray, px
            ry = (a.y - tm.y) * frame_h
            raw_x += rx * PINCH_CURSOR_THUMB_OFFSET_X
            raw_y += ry * PINCH_CURSOR_THUMB_OFFSET_X
            if PINCH_CURSOR_THUMB_OFFSET_Y:
                im = hand_landmarks[HAND_SCALE_KNUCKLE_A]   # index MCP
                px, py = -ry, rx          # ray rotated 90 deg
                ix = (im.x - tm.x) * frame_w
                iy = (im.y - tm.y) * frame_h
                if px * ix + py * iy < 0:  # make +Y face the index side
                    px, py = -px, -py
                raw_x += px * PINCH_CURSOR_THUMB_OFFSET_Y
                raw_y += py * PINCH_CURSOR_THUMB_OFFSET_Y

        # Close counter-movement: as the pinch progresses the thumb itself
        # travels toward the index, dragging the anchored cursor with it.
        # Express the cursor point in a rigid hand frame — origin at the
        # wrist, basis u = wrist->index MCP and v = rot90(u), segments the
        # fingers cannot move — and track its coordinates while the hand
        # is open (tracking rate 1-progress: full when open, frozen when
        # closed). The drawn cursor is pulled toward the point those
        # remembered coordinates land on in the CURRENT frame: the thumb's
        # own close travel is cancelled (a counter-movement, growing with
        # the pinch progress) while real hand motion — translation,
        # rotation, zoom — still moves the cursor 1:1.
        if PINCH_CURSOR_COMPENSATE > 0.0:
            wr = hand_landmarks[HAND_SCALE_PALM_A]
            im = hand_landmarks[HAND_SCALE_KNUCKLE_A]
            wx, wy = wr.x * frame_w, wr.y * frame_h
            ux, uy = im.x * frame_w - wx, im.y * frame_h - wy
            den = ux * ux + uy * uy
            if den > 1e-9:
                dxp, dyp = raw_x - wx, raw_y - wy
                a_ = (dxp * ux + dyp * uy) / den
                b_ = (-dxp * uy + dyp * ux) / den   # v = (-uy, ux)
                if self._cursor_ref is None:
                    self._cursor_ref = (a_, b_)
                else:
                    k = 1.0 - self.progress
                    ra, rb = self._cursor_ref
                    self._cursor_ref = (ra + (a_ - ra) * k,
                                        rb + (b_ - rb) * k)
                ra, rb = self._cursor_ref
                hat_x = wx + ra * ux - rb * uy
                hat_y = wy + ra * uy + rb * ux
                raw_x += (hat_x - raw_x) * PINCH_CURSOR_COMPENSATE
                raw_y += (hat_y - raw_y) * PINCH_CURSOR_COMPENSATE

        self._advance_cursor(raw_x, raw_y, dt, age_s)
        self._advance_machine(now)

    def _advance_cursor(self, raw_x, raw_y, dt, age_s):
        """Filter the anchor point, then extrapolate the OUTPUT forward by the
        filter's velocity times the detection age (never feed the
        extrapolation back into the filter, or the correction compounds)."""
        fx = self._fx(raw_x, dt)
        fy = self._fy(raw_y, dt)
        lead = min(age_s, PINCH_EXTRAP_MAX_S)
        self.cursor = (fx + self._fx.velocity * lead,
                       fy + self._fy.velocity * lead)

    def _advance_machine(self, now):
        """Edge-triggered close/open machine on ``self.ratio``.

        Identical whichever gesture produced the ratio — that is the whole
        point of normalizing the fist into pinch units upstream.
        """
        self.pinching = False
        if not self._initialised:
            # A hand that appears already closed starts in the closed state
            # WITHOUT firing — a fist entering the frame cannot click.
            self.closed = self.ratio < PINCH_CLOSE_RATIO
            self.press_cursor = self.cursor
            self._initialised = True
        elif not self.closed:
            if self.ratio < PINCH_CLOSE_RATIO:
                if self._close_frames == 0:
                    # Close gesture starts here: latch the press cursor.
                    self.press_cursor = self.cursor
                self._close_frames += 1
                if self._close_frames >= PINCH_DEBOUNCE_CLOSE_FRAMES:
                    self.closed = True
                    self.pinching = True  # fires exactly once per close
                    self._close_frames = 0
            else:
                self._close_frames = 0
                self.press_cursor = self.cursor  # track live while open
        else:
            if self.ratio > PINCH_RELEASE_RATIO:
                self._open_frames += 1
                if self._open_frames >= PINCH_DEBOUNCE_RELEASE_FRAMES:
                    self.closed = False
                    self._open_frames = 0
            else:
                self._open_frames = 0
        self.last_seen = now


# One machine per stable hand id ("Left" / "Right").
_pinch_machines: dict[str, _HandPinch] = {}
_last_update_t: float | None = None
_result_age_s: float = 0.0

# Hands claimed by the UI for the current frame (see ``reserve_hand``).
_reserved_hands: set[str] = set()


def reserve_hand(hand_id):
    """Claim a hand for a UI widget for the rest of this frame.

    Buttons float ON TOP of the scene, and the two read the same pinch
    snapshot independently — so closing your hand on the "Magnets" button
    used to press the button *and* drop a magnet underneath it, because
    nothing told the scene that a button had already taken that gesture.
    ``UIManager`` reserves any hand sitting over a live button, and
    ``pinch_state`` then withholds the closing EVENT from it, the way a
    click on a dialog does not also reach the page behind it.

    Cleared at the start of every ``update_pinches`` call, so a reservation
    can never outlive the frame that made it.
    """
    _reserved_hands.add(hand_id)


def hand_reserved(hand_id):
    """True while a UI widget owns this hand's closing event this frame."""
    return hand_id in _reserved_hands


def update_pinches(hand_result, frame_w, frame_h, now=None, received_t=None):
    """Advance every hand's pinch machine. Call exactly ONCE per rendered
    frame (``UIManager.update`` does this) before any snapshot read.

    ``received_t`` is the ``time.monotonic()`` instant the detection result
    was received (from ``detectors.latest_hand_packet``); the derived age
    drives the cursor's latency extrapolation and is exposed through
    ``result_age_s()`` for the debug HUD. ``None`` means "age unknown" and
    disables extrapolation.

    Machines for hands missing from this frame have their one-frame
    ``pinching`` event cleared (nothing may consume it late) and are kept
    warm for ``PINCH_TRACK_GRACE_S`` so a brief tracking dropout resumes
    mid-hold instead of cold-starting; beyond the grace period they are
    dropped (and a reappearing hand re-enters via the
    no-fire-if-already-closed rule).
    """
    global _last_update_t, _result_age_s
    if now is None:
        now = time.monotonic()
    _last_update_t = now
    _result_age_s = (min(max(now - received_t, 0.0), 1.0)
                     if received_t is not None else 0.0)
    # UI reservations last exactly one frame; this is the once-per-frame
    # entry point, so clearing here is what guarantees that.
    _reserved_hands.clear()

    advanced = set()
    if hand_result is not None:
        for i, hand_landmarks in enumerate(hand_result.hand_landmarks):
            hid = hand_id(hand_result, i)
            machine = _pinch_machines.get(hid)
            if machine is None:
                machine = _HandPinch()
                _pinch_machines[hid] = machine
            # Per-hand dt, clamped: survives dropouts and startup.
            dt = now - machine.last_seen if machine.last_seen else 1.0 / 30.0
            dt = min(max(dt, 1.0 / 120.0), 0.25)
            machine.advance(hand_landmarks, frame_w, frame_h, dt, now,
                            _result_age_s)
            advanced.add(hid)

    for hid, machine in list(_pinch_machines.items()):
        if hid not in advanced:
            # The edge event is one frame only — a hand that vanished right
            # after firing must not keep a stale True through the grace.
            machine.pinching = False
        if now - machine.last_seen > PINCH_TRACK_GRACE_S:
            del _pinch_machines[hid]


def result_age_s():
    """Age (s) of the detection result used by the last ``update_pinches``
    call — the same value the cursor extrapolation used. 0.0 when unknown."""
    return _result_age_s


def pinch_state(hand_id):
    """Read-only pinch snapshot for one hand: ``(pinching, held, (mx, my))``.

    * ``pinching`` — edge event, True only on the frame the pinch closed.
      Use it to *trigger* actions (button click, grab initiation).
    * ``held`` — level state, True while the machine is closed (hysteresis
      + debounce keep it stable). Use it to *maintain* a triggered gesture.
    * ``(mx, my)`` — smoothed, latency-compensated pinch cursor in pixels;
      always provided for hover/cursor use.

    **This is the SCENE-facing read, and it honours UI reservations**: a
    hand sitting over a live button reports ``pinching = False``, so
    closing your hand on a button presses the button without also
    spawning whatever the scene underneath does with a new pinch (see
    ``reserve_hand``). Only the *event* is withheld — ``held`` still
    reports the truth, so an object already being dragged survives being
    carried across a button instead of being dropped on it. Widgets that
    need the raw machine (buttons, the cursor overlay, the debug HUD, the
    state payload) use ``pinch_info`` / ``pinch_infos`` instead.

    Reading never mutates state, so any number of widgets can query the
    same hand in one frame. Requires ``update_pinches()`` to have run this
    frame; unknown ids return ``(False, False, (0.0, 0.0))``.
    """
    machine = _pinch_machines.get(hand_id)
    if machine is None:
        return False, False, (0.0, 0.0)
    pinching = machine.pinching and hand_id not in _reserved_hands
    return pinching, machine.closed, machine.cursor


def pinch_info(hand_id):
    """Full pinch machine for one hand (or ``None`` if unknown).

    The returned ``_HandPinch`` is the live per-frame snapshot — treat it
    as READ-ONLY; it only mutates inside ``update_pinches``. Richer than
    ``pinch_state``: exposes ``ratio``, ``progress``, ``state``,
    ``press_cursor`` and ``last_seen`` for the cursor overlay, hover-latch
    buttons and the debug HUD.
    """
    return _pinch_machines.get(hand_id)


def pinch_infos():
    """Snapshot list of ``(hand_id, machine)`` for every tracked hand
    (including grace-window survivors). Read-only, same contract as
    ``pinch_info``."""
    return list(_pinch_machines.items())
