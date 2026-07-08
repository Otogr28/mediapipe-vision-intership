"""One-Euro smoothing + velocity extrapolation for the body pose.

This gives the avatar's body the same smooth-yet-snappy feel the pinch cursor
has (see ``gestures._HandPinch``). Body pose runs at ~13 fps on CPU and lands
one inference behind the live frame, so fed raw it stutters and lags — the
hands feel fine only because their cursor is already One-Euro filtered and
extrapolated. ``PoseSmoother`` applies the same two ideas to every pose
landmark:

* **One-Euro filter** — adaptive low-pass: hard smoothing at rest (kills the
  jitter and softens tracking teleports into a realistic glide), light while
  moving fast (no added lag).
* **Velocity extrapolation** — the OUTPUT is pushed forward by the filtered
  velocity times the result's age (capped), so between the sparse pose results
  the body keeps gliding instead of freezing, and the inference latency is
  partly hidden. The extrapolation is never fed back into the filter.

Both the 2D image landmarks and the 3D world landmarks are filtered. The
smoothed values are handed back as lightweight landmark-like objects so the
rest of the pipeline (``web.state`` serialization, ``drawing``) is unchanged.
"""

from collections import namedtuple

from config import (POSE_BETA, POSE_EXTRAP_MAX_S, POSE_MIN_CUTOFF,
                    POSE_SMOOTH_RESET_GAP_S)
from detection.gestures import _OneEuroFilter

# Quack like MediaPipe's NormalizedLandmark / Landmark so downstream code that
# reads .x/.y/.visibility/.z keeps working unchanged.
_LM2D = namedtuple("_LM2D", "x y visibility")
_LM3D = namedtuple("_LM3D", "x y z")


class PoseSmoother:
    def __init__(self):
        self._n = 0
        self._fx = self._fy = None            # 2D image filters
        self._wx = self._wy = self._wz = None  # 3D world filters
        self._sx = self._sy = None            # last smoothed 2D
        self._swx = self._swy = self._swz = None  # last smoothed world
        self._vis = None
        self._has_world = False
        self._last_t = None

    def _init(self, n):
        def bank():
            return [_OneEuroFilter(POSE_MIN_CUTOFF, POSE_BETA) for _ in range(n)]
        self._fx, self._fy = bank(), bank()
        self._wx, self._wy, self._wz = bank(), bank(), bank()
        self._sx = [0.0] * n
        self._sy = [0.0] * n
        self._swx = [0.0] * n
        self._swy = [0.0] * n
        self._swz = [0.0] * n
        self._vis = [1.0] * n
        self._n = n
        self._last_t = None

    def reset(self):
        """Drop filter state — the next result eases in fresh (no snap across a
        gap when pose was toggled off and back on)."""
        self._n = 0
        self._last_t = None

    def update(self, pose_landmarks, pose_world, t):
        """Feed ONE new pose result (call once per distinct result)."""
        if not pose_landmarks:
            return
        n = len(pose_landmarks)
        if self._n != n:
            self._init(n)
        if self._last_t is None:
            dt = 1.0 / 20.0
        else:
            gap = t - self._last_t
            if gap > POSE_SMOOTH_RESET_GAP_S:
                self._init(n)     # long gap → start clean, no snap
                dt = 1.0 / 20.0
            else:
                dt = max(gap, 1e-3)
        self._last_t = t

        for i in range(n):
            lm = pose_landmarks[i]
            self._sx[i] = self._fx[i](lm.x, dt)
            self._sy[i] = self._fy[i](lm.y, dt)
            vis = getattr(lm, "visibility", None)
            self._vis[i] = 1.0 if vis is None else vis

        self._has_world = bool(pose_world) and len(pose_world) == n
        if self._has_world:
            for i in range(n):
                w = pose_world[i]
                self._swx[i] = self._wx[i](w.x, dt)
                self._swy[i] = self._wy[i](w.y, dt)
                self._swz[i] = self._wz[i](w.z, dt)

    def sample(self, now):
        """Return ``(pose_2d, pose_world)`` extrapolated to ``now`` — lists of
        landmark-like objects, or ``(None, None)`` if nothing has been fed."""
        if self._last_t is None or self._n == 0:
            return None, None
        lead = min(max(now - self._last_t, 0.0), POSE_EXTRAP_MAX_S)
        pose = [
            _LM2D(self._sx[i] + self._fx[i].velocity * lead,
                  self._sy[i] + self._fy[i].velocity * lead,
                  self._vis[i])
            for i in range(self._n)
        ]
        world = None
        if self._has_world:
            world = [
                _LM3D(self._swx[i] + self._wx[i].velocity * lead,
                      self._swy[i] + self._wy[i].velocity * lead,
                      self._swz[i] + self._wz[i].velocity * lead)
                for i in range(self._n)
            ]
        return pose, world
