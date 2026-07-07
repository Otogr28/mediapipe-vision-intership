"""High-level gestures derived from raw MediaPipe landmarks.

The only gesture implemented is the thumb-index **pinch**, built from the
techniques production hand-tracking stacks use:

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
* **Thumb-anchored cursor**: the cursor rides the THUMB TIP (landmark 4).
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

from config import (PINCH_CLOSE_RATIO, PINCH_CURSOR_BETA,
                    PINCH_CURSOR_COMPENSATE, PINCH_CURSOR_MIN_CUTOFF,
                    PINCH_CURSOR_THUMB_OFFSET_X, PINCH_CURSOR_THUMB_OFFSET_Y,
                    PINCH_DEBOUNCE_CLOSE_FRAMES, PINCH_DEBOUNCE_RELEASE_FRAMES,
                    PINCH_EXTRAP_MAX_S, PINCH_RATIO_BETA,
                    PINCH_RATIO_MIN_CUTOFF, PINCH_RELEASE_RATIO,
                    PINCH_TRACK_GRACE_S, PINCH_Z_WEIGHT)

PINCH_LANDMARK_A = 4   # thumb tip (hand) — also the cursor anchor
PINCH_LANDMARK_B = 8   # index finger tip (hand)

THUMB_MCP = 2          # base of the thumb ray for the cursor offset

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
        # Cursor latched where the close gesture STARTED (close debounce
        # 0->1); consumers hit-test clicks against this so the hand drifting
        # during the close cannot slide the click off its target.
        self.press_cursor = (0.0, 0.0)
        self.ratio = None            # filtered pinch ratio (None until seen)
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
        b = hand_landmarks[PINCH_LANDMARK_B]
        ax, ay = a.x * frame_w, a.y * frame_h
        bx, by = b.x * frame_w, b.y * frame_h

        scale = hand_scale(hand_landmarks, frame_w, frame_h)
        if scale <= 0.0:
            # Degenerate landmarks; keep the previous state, fire nothing.
            self.pinching = False
            self.last_seen = now
            return

        # 3D tip distance: z is wrist-relative in ~x-normalized units, so
        # frame_w puts it in pixels like dx/dy; missing z degrades to 2D.
        dz = ((getattr(a, "z", 0.0) - getattr(b, "z", 0.0))
              * frame_w * PINCH_Z_WEIGHT)
        dist = math.sqrt((ax - bx) ** 2 + (ay - by) ** 2 + dz * dz)
        self.ratio = self._fr(dist / scale, dt)

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

        fx = self._fx(raw_x, dt)
        fy = self._fy(raw_y, dt)
        lead = min(age_s, PINCH_EXTRAP_MAX_S)
        self.cursor = (fx + self._fx.velocity * lead,
                       fy + self._fy.velocity * lead)

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

    Reading never mutates state, so any number of widgets can query the
    same hand in one frame. Requires ``update_pinches()`` to have run this
    frame; unknown ids return ``(False, False, (0.0, 0.0))``.
    """
    machine = _pinch_machines.get(hand_id)
    if machine is None:
        return False, False, (0.0, 0.0)
    return machine.pinching, machine.closed, machine.cursor


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
