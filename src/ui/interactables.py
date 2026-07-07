import math
import random
import time
from collections import deque

import cv2
import numpy as np

from config import (BH_DEFAULT_POS_FACTOR, BH_DISK_BRIGHTNESS,
                    BH_DISK_INNER_FACTOR, BH_DISK_OUTER_FACTOR,
                    BH_DISK_ROTATION_SPEED, BH_DISK_TILT_RAD,
                    BH_EINSTEIN_RADIUS_PX, BH_GRAB_RADIUS,
                    SIXSEVEN_FLASH_FRAMES, SIXSEVEN_HYSTERESIS,
                    SIXSEVEN_MIN_VISIBILITY)
from detection.gestures import hand_id, pinch_state

POSE_LEFT_ELBOW = 13
POSE_RIGHT_ELBOW = 14
POSE_LEFT_WRIST = 15
POSE_RIGHT_WRIST = 16


FINGERTIP_INDICES = [0, 4, 8, 12, 16, 20]
FINGER_RADIUS = 14
PUSH_FORCE = 18.0
MAX_SPEED = 22.0
FRICTION = 0.985
GRAB_RADIUS = 80      # max distance from midpoint to sphere center to initiate grab


class BouncingSphere:
    def __init__(self, frame_width, frame_height, radius=40):
        self.radius = radius
        self.w = frame_width
        self.h = frame_height
        self.x = float(frame_width // 2)
        self.y = float(frame_height // 2)
        self.vx = random.choice([-5.0, 5.0])
        self.vy = random.choice([-4.0, 4.0])
        self.grabbed = False
        self.grab_hand = None      # owner: hand_id that initiated the grab
        self.grab_offset_x = 0.0
        self.grab_offset_y = 0.0

    def update(self, hand_result, pose_landmarks):
        if self.grabbed:
            # Owner latch: only the hand that initiated the grab may keep
            # it — another hand pinch-holding elsewhere on screen must not
            # steal the sphere. Reading that hand's machine directly (not
            # just the hands in this frame's result) lets the grab ride out
            # a short tracking dropout; past the grace window the machine
            # is dropped, `held` reads False and the sphere releases.
            _, held, (mx, my) = pinch_state(self.grab_hand)
            if held:
                new_x = mx + self.grab_offset_x
                new_y = my + self.grab_offset_y
                self.vx = new_x - self.x
                self.vy = new_y - self.y
                self.x = new_x
                self.y = new_y
            else:
                self.grabbed = False
                self.grab_hand = None

        if not self.grabbed and hand_result is not None:
            for i, hand_landmarks in enumerate(hand_result.hand_landmarks):
                hid = hand_id(hand_result, i)
                pinching, held, (mx, my) = pinch_state(hid)

                # Only the fresh close event (`pinching`) can initiate a
                # grab, so an already-closed hand sliding over the sphere
                # will not pick it up.
                sphere_dist = ((self.x - mx) ** 2 + (self.y - my) ** 2) ** 0.5
                if pinching and sphere_dist < GRAB_RADIUS:
                    self.grab_hand = hid
                    self.grab_offset_x = self.x - mx
                    self.grab_offset_y = self.y - my
                    self.vx = 0.0
                    self.vy = 0.0
                    self.grabbed = True
                    break

            if not self.grabbed:
                for hand_landmarks in hand_result.hand_landmarks:
                    for idx in FINGERTIP_INDICES:
                        lm = hand_landmarks[idx]
                        fx = lm.x * self.w
                        fy = lm.y * self.h
                        dx = self.x - fx
                        dy = self.y - fy
                        dist = (dx ** 2 + dy ** 2) ** 0.5
                        contact_dist = self.radius + FINGER_RADIUS
                        if dist < contact_dist and dist > 0:
                            nx = dx / dist
                            ny = dy / dist
                            overlap = contact_dist - dist
                            impulse = PUSH_FORCE * (1 + overlap / contact_dist)
                            self.vx += nx * impulse
                            self.vy += ny * impulse

        if not self.grabbed:
            self.vx *= FRICTION
            self.vy *= FRICTION

            speed = (self.vx ** 2 + self.vy ** 2) ** 0.5
            if speed > MAX_SPEED:
                self.vx = self.vx / speed * MAX_SPEED
                self.vy = self.vy / speed * MAX_SPEED

            self.x += self.vx
            self.y += self.vy

            if self.x - self.radius <= 0:
                self.x = float(self.radius)
                self.vx = abs(self.vx)
            elif self.x + self.radius >= self.w:
                self.x = float(self.w - self.radius)
                self.vx = -abs(self.vx)

            if self.y - self.radius <= 0:
                self.y = float(self.radius)
                self.vy = abs(self.vy)
            elif self.y + self.radius >= self.h:
                self.y = float(self.h - self.radius)
                self.vy = -abs(self.vy)

    def to_state(self):
        """Serializable snapshot for the web frontend. The physics stays
        here — the browser only renders the resolved position."""
        return {
            "type": "sphere",
            "x": round(self.x, 1),
            "y": round(self.y, 1),
            "r": self.radius,
            "grabbed": self.grabbed,
        }

    def draw(self, frame):
        cx, cy = int(self.x), int(self.y)
        if self.grabbed:
            cv2.circle(frame, (cx, cy), self.radius + 10, (0, 200, 80), 3)
            cv2.circle(frame, (cx, cy), self.radius, (0, 220, 100), -1)
            cv2.circle(frame, (cx - self.radius // 4, cy - self.radius // 4), self.radius // 4, (120, 255, 180), -1)
        else:
            cv2.circle(frame, (cx, cy), self.radius + 6, (0, 50, 160), -1)
            cv2.circle(frame, (cx, cy), self.radius, (0, 120, 255), -1)
            cv2.circle(frame, (cx - self.radius // 4, cy - self.radius // 4), self.radius // 4, (100, 210, 255), -1)


class BlackHole:
    """Schwarzschild-lensing black hole. Drawable + pinch-draggable.

    The lensing is computed entirely in a GLSL fragment shader by an
    externally-owned `LensingRenderer` (passed in at construction so a
    single GL context can be shared between multiple effects). This
    class only owns the BH's screen position and grab state — it has no
    physics, no collisions, and does not interact with other
    interactables (the project keeps BH and sphere in separate UI states
    so coexistence is not a concern).
    """

    def __init__(self, frame_width, frame_height, renderer,
                 einstein_radius_px=BH_EINSTEIN_RADIUS_PX,
                 disk_inner_factor=BH_DISK_INNER_FACTOR,
                 disk_outer_factor=BH_DISK_OUTER_FACTOR,
                 disk_tilt_rad=BH_DISK_TILT_RAD,
                 disk_brightness=BH_DISK_BRIGHTNESS,
                 disk_rotation_speed=BH_DISK_ROTATION_SPEED):
        self.w = frame_width
        self.h = frame_height
        fx, fy = BH_DEFAULT_POS_FACTOR
        self.x = float(frame_width * fx)
        self.y = float(frame_height * fy)
        self.einstein_radius_px = einstein_radius_px
        # Disk extent is stored as a multiplier of the Einstein radius so
        # tuning `einstein_radius_px` alone keeps the disk's proportions
        # to the BH intact.
        self.disk_inner_factor = disk_inner_factor
        self.disk_outer_factor = disk_outer_factor
        self.disk_tilt_rad = disk_tilt_rad
        self.disk_brightness = disk_brightness
        self.disk_rotation_speed = disk_rotation_speed
        self.grabbed = False
        self.grab_hand = None      # owner: hand_id that initiated the drag
        self.grab_offset_x = 0.0
        self.grab_offset_y = 0.0
        self._renderer = renderer
        # Anchor for the rotation clock so successive spawns start from
        # phase zero instead of inheriting elapsed time from the process.
        self._spawn_time = time.monotonic()

    def update(self, hand_result, pose_landmarks):
        if self.grabbed:
            # Owner latch — same rule as BouncingSphere: only the hand
            # that initiated the drag may move it; it survives a tracking
            # dropout within the pinch grace window and releases when the
            # fingers open (or the hand expires past the grace).
            _, held, (mx, my) = pinch_state(self.grab_hand)
            if held:
                self.x = mx + self.grab_offset_x
                self.y = my + self.grab_offset_y
            else:
                self.grabbed = False
                self.grab_hand = None

        if not self.grabbed and hand_result is not None:
            for i in range(len(hand_result.hand_landmarks)):
                hid = hand_id(hand_result, i)
                pinching, _, (mx, my) = pinch_state(hid)

                dist = ((self.x - mx) ** 2 + (self.y - my) ** 2) ** 0.5
                if pinching and dist < BH_GRAB_RADIUS:
                    self.grab_hand = hid
                    self.grab_offset_x = self.x - mx
                    self.grab_offset_y = self.y - my
                    self.grabbed = True
                    break

    def to_state(self):
        """Serializable snapshot for the web frontend. The lensing itself is
        a full-frame shader — in web mode the browser runs the WebGL port of
        it over the video, so only the parameters travel."""
        E = self.einstein_radius_px
        return {
            "type": "black_hole",
            "x": round(self.x, 1),
            "y": round(self.y, 1),
            "einstein_px": E,
            "disk_inner_px": round(E * self.disk_inner_factor, 1),
            "disk_outer_px": round(E * self.disk_outer_factor, 1),
            "disk_tilt_rad": self.disk_tilt_rad,
            "disk_brightness": self.disk_brightness,
            "rotation_speed": self.disk_rotation_speed,
            "disk_t": round((time.monotonic() - self._spawn_time) % 1000.0, 3),
            "grabbed": self.grabbed,
        }

    def draw(self, frame):
        if self._renderer is None:
            # Web mode: no GL context on the backend — the browser shader
            # renders the lensing from to_state()'s parameters instead.
            return
        E = self.einstein_radius_px
        # Wrap elapsed time to keep GPU float32 precision intact over
        # long runs; the rotation phase is periodic anyway.
        elapsed = (time.monotonic() - self._spawn_time) % 1000.0
        lensed = self._renderer.render(
            frame,
            bh_center=(self.x, self.y),
            einstein_px=E,
            disk_inner_px=E * self.disk_inner_factor,
            disk_outer_px=E * self.disk_outer_factor,
            disk_tilt_rad=self.disk_tilt_rad,
            disk_brightness=self.disk_brightness,
            time_seconds=elapsed,
            rotation_speed=self.disk_rotation_speed,
        )
        np.copyto(frame, lensed)


class SixSevenCounter:
    """6 7 gesture counter — port of mannygonzalezj7/67counter.

    Watches both arms in the pose landmarks and increments on the rising
    edge of "wrist above elbow" per side. Each arm latches independently
    with a hysteresis band (`SIXSEVEN_HYSTERESIS`) so jitter near the
    elbow line cannot re-fire the count without a clear reset stroke.
    """

    def __init__(self, frame_width, frame_height):
        self.w = frame_width
        self.h = frame_height
        self.count = 0
        # Latch state per side: True when that side is currently "armed"
        # (wrist clearly above elbow) and waiting for a reset stroke.
        self._left_armed = False
        self._right_armed = False
        # Decay counter for the flash overlay, in frames.
        self._flash = 0

    def _side_armed(self, prev_armed, elbow_lm, wrist_lm):
        """Hysteresis latch for one arm.

        Returns ``(new_armed, fired)`` where ``fired`` is True only on the
        frame the wrist *just* crossed above the elbow. Low-visibility
        landmarks leave the latch unchanged and never fire — so a brief
        tracking dropout cannot phantom-trigger a count.
        """
        e_vis = elbow_lm.visibility if elbow_lm.visibility is not None else 1.0
        w_vis = wrist_lm.visibility if wrist_lm.visibility is not None else 1.0
        if e_vis < SIXSEVEN_MIN_VISIBILITY or w_vis < SIXSEVEN_MIN_VISIBILITY:
            return prev_armed, False

        dy = elbow_lm.y - wrist_lm.y  # >0 when wrist is above elbow
        if not prev_armed and dy > SIXSEVEN_HYSTERESIS:
            return True, True
        if prev_armed and dy < -SIXSEVEN_HYSTERESIS:
            return False, False
        return prev_armed, False

    def to_state(self):
        """Serializable snapshot for the web frontend."""
        flash = (self._flash / SIXSEVEN_FLASH_FRAMES
                 if SIXSEVEN_FLASH_FRAMES else 0.0)
        return {"type": "sixseven", "count": self.count,
                "flash": round(flash, 3)}

    def update(self, hand_result, pose_landmarks):
        if not pose_landmarks:
            return

        self._left_armed, left_fired = self._side_armed(
            self._left_armed,
            pose_landmarks[POSE_LEFT_ELBOW],
            pose_landmarks[POSE_LEFT_WRIST],
        )
        self._right_armed, right_fired = self._side_armed(
            self._right_armed,
            pose_landmarks[POSE_RIGHT_ELBOW],
            pose_landmarks[POSE_RIGHT_WRIST],
        )

        if left_fired:
            self.count += 1
            self._flash = SIXSEVEN_FLASH_FRAMES
        if right_fired:
            self.count += 1
            self._flash = SIXSEVEN_FLASH_FRAMES

        if self._flash > 0:
            self._flash -= 1

    def draw(self, frame):
        flash_t = self._flash / SIXSEVEN_FLASH_FRAMES if SIXSEVEN_FLASH_FRAMES else 0.0

        label = "6 7"
        count_text = str(self.count)
        font = cv2.FONT_HERSHEY_SIMPLEX
        label_scale = 0.9
        count_scale = 2.2 + 0.4 * flash_t
        label_thick = 2
        count_thick = 4

        (lw, lh), _ = cv2.getTextSize(label, font, label_scale, label_thick)
        (cw, ch), _ = cv2.getTextSize(count_text, font, count_scale, count_thick)

        pad_x, pad_y, gap = 24, 18, 10
        box_w = max(lw, cw) + pad_x * 2
        box_h = lh + ch + gap + pad_y * 2
        box_x = (self.w - box_w) // 2
        box_y = 12

        overlay = frame.copy()
        cv2.rectangle(overlay, (box_x, box_y), (box_x + box_w, box_y + box_h),
                      (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)

        # Border flashes green on a fresh count, then fades to neutral.
        border = (
            int(120 + (0 - 120) * flash_t),
            int(120 + (220 - 120) * flash_t),
            int(120 + (100 - 120) * flash_t),
        )
        cv2.rectangle(frame, (box_x, box_y), (box_x + box_w, box_y + box_h),
                      border, 2)

        lx = box_x + (box_w - lw) // 2
        ly = box_y + pad_y + lh
        cv2.putText(frame, label, (lx, ly), font, label_scale,
                    (200, 200, 200), label_thick, cv2.LINE_AA)

        cx = box_x + (box_w - cw) // 2
        cy = ly + gap + ch
        cv2.putText(frame, count_text, (cx, cy), font, count_scale,
                    (255, 255, 255), count_thick, cv2.LINE_AA)


# --- Slingshot projectile experiment (SI units) -------------------------
# The whole simulation runs in SI units — metres, seconds, kilograms, newtons.
# Two scale constants bridge that physical world to the video's pixels/frames:
SLING_PX_PER_M = 100.0       # screen scale: 100 px = 1 m (frame ~ 19.2 x 10.8 m)
SLING_FRAME_DT = 1.0 / 30.0  # simulated time one video frame represents (s)
# Fixed-timestep integration — the standard technique for stable real-time
# physics: each frame banks `time_scale * SLING_FRAME_DT` of simulated time
# into an accumulator and the world advances in whole SLING_PHYS_DT steps.
# The sim-speed buttons change how MANY steps run per frame, never the step
# size, so accuracy and stability are identical at every speed.
SLING_PHYS_DT = 1.0 / 120.0  # physics step (s)
SLING_MAX_SUBSTEPS = 32      # per-frame cap; drops sim debt rather than stall

SLING_G = 9.81               # gravitational acceleration (m/s^2), Earth
SLING_BALL_MASS = 1.0        # mass of every ball (kg); equal mass keeps the
                             # ball-vs-ball collision a clean velocity exchange
# Quadratic aerodynamic drag F = -(1/2) rho Cd A |v| v — the correct regime
# for a ball at m/s speeds (Re ~ 1e5); linear Stokes drag only fits dust.
SLING_AIR_DENSITY = 1.225    # rho: air at sea level (kg/m^3)
SLING_DRAG_CD = 0.47         # Cd: smooth sphere
SLING_TIME_SCALES = (0.25, 0.5, 1.0, 2.0, 4.0)  # sim speeds the UI steps through

# Elastic band — energy model (Yeats, "Physical modeling of real-world
# slingshots", arXiv:1604.00049): the drawn band stores E = 1/2 k x^2
# (Hooke's-law draw force F = k x) but only a fraction of it returns as
# projectile KE — latex hysteresis plus the band/pouch's own kinetic energy
# eat 10-25%. Launch speed follows as v0 = x * sqrt(k * eff / m).
SLING_BAND_K = 44.2          # band spring constant (N/m), real latex band
SLING_BAND_EFF = 0.75        # stored-energy fraction delivered to the ball;
                             # a full 2.6 m pull -> ~15 m/s
SLING_MAX_PULL_PX = 260      # cap on pull-back distance (screen px)
SLING_GRAB_RADIUS_PX = 90    # max screen distance from the anchor to start aiming

SLING_WALL_RESTITUTION = 0.7
SLING_GROUND_RESTITUTION = 0.55
SLING_FRICTION_MU = 0.5      # Coulomb friction coefficient for surface contacts:
                             # bounce tangential impulse capped by the friction
                             # cone |jt| <= mu*|jn|; sliding decelerates at mu*g
SLING_COLLISION_RESTITUTION = 0.85  # bounciness of ball-vs-ball impacts
SLING_REST_SPEED = 0.3       # m/s; below this on the floor a ball is "at rest"

SLING_RADIUS_PX = 22         # ball radius on screen (px) -> 0.22 m
SLING_TRAIL_LEN = 40
SLING_MAX_PROJECTILES = 8
SLING_PREDICT_TIME_S = 1.5   # how far ahead the dotted aim preview simulates
SLING_PREDICT_SAMPLE = 4     # one preview dot every N physics steps
SLING_CONTACT_DECAY = 0.6    # per-frame fade of the transient contact-force arrow

# Force-vector overlay.
SLING_FORCE_PX_PER_N = 6.0     # arrow length drawn per newton (weight ~ 59 px)
SLING_FORCE_MAX_PX = 130       # cap so bounce impulses don't span the screen
SLING_MIN_FORCE_DRAW_N = 0.25  # skip arrows for negligible forces
SLING_ARROW_HEAD_PX = 9        # fixed arrowhead size, independent of length
SLING_COL_WEIGHT = (0, 180, 255)   # BGR amber — weight  m*g
SLING_COL_DRAG = (255, 200, 0)     # BGR cyan  — air drag -b*v
SLING_COL_NORMAL = (0, 235, 0)     # BGR green — contact / normal reaction
SLING_COL_NET = (240, 240, 240)    # BGR white — net force


class _Projectile:
    __slots__ = ("id", "x", "y", "vx", "vy", "trail", "resting", "sliding",
                 "cfx", "cfy")

    def __init__(self, x, y, vx, vy, pid=0):
        # Stable id so the web frontend can accumulate per-ball trails
        # client-side (the trail itself is NOT streamed — one point per
        # frame per id reconstructs it exactly).
        self.id = pid
        self.x = x     # position, metres (screen frame; +y points down)
        self.y = y
        self.vx = vx   # velocity, m/s
        self.vy = vy
        self.trail = deque(maxlen=SLING_TRAIL_LEN)
        self.resting = False
        self.sliding = False  # skidding along the floor under Coulomb friction
        # Net contact force this frame (N) — floor/wall/ball reactions — kept
        # only for the force overlay. Weight and drag are recomputed from state.
        self.cfx = 0.0
        self.cfy = 0.0


class Slingshot:
    """Projectile-motion experiment in SI units: pull back and release to launch.

    Physics runs in metres / seconds / kilograms / newtons; ``SLING_PX_PER_M``
    maps that world onto the video's pixels. A ball rests on a fixed anchor; a
    pinch near it grabs the ball, the hand pulls it back (rubber-band aim,
    capped) and a dotted arc previews the shot while a HUD reads out launch
    angle, speed (m/s) and kinetic energy (J).

    The simulation uses the standard real-time techniques: a fixed-timestep
    accumulator (``SLING_PHYS_DT`` sub-steps, so the adjustable sim speed never
    changes the step size), classic 4th-order Runge-Kutta integration of free
    flight under gravity plus quadratic aerodynamic drag (-1/2 rho Cd A |v| v,
    real air/sphere constants), and impulse-based collision response with
    restitution and positional correction for walls, floor and ball-vs-ball
    impacts. Launch speed comes from the slingshot energy model (Yeats,
    arXiv:1604.00049): the Hooke's-law band stores E = 1/2 k x^2 and delivers
    ``SLING_BAND_EFF`` of it as KE (hysteresis + band inertia losses), so
    v0 = x * sqrt(k * eff / m). Surface contacts use the Coulomb friction
    cone (|jt| <= mu * |jn| on bounces, mu*m*g sliding friction on the floor).
    Every ball draws the force vectors acting on it (weight, drag, contact,
    net). Up to ``SLING_MAX_PROJECTILES`` shots coexist (oldest
    dropped past the cap). ``time_scale`` (stepped by the UI's -/+ buttons
    through ``SLING_TIME_SCALES``) slows or speeds the whole world. Aiming
    reads the shared per-frame pinch snapshot (see detection/gestures.py).
    """

    def __init__(self, frame_width, frame_height):
        self.w_px = frame_width
        self.h_px = frame_height
        # Frame extent and ball radius expressed in metres for the physics.
        self.w = frame_width / SLING_PX_PER_M
        self.h = frame_height / SLING_PX_PER_M
        self.r = SLING_RADIUS_PX / SLING_PX_PER_M
        self.anchor_x = (frame_width * 0.5) / SLING_PX_PER_M
        self.anchor_y = (frame_height * 0.82) / SLING_PX_PER_M
        self.projectiles = []
        # Aim state: while aiming, (pull_x, pull_y) is the clamped ball position
        # in metres.
        self.aiming = False
        self.aim_hand = None       # owner: hand_id that initiated the aim
        self.pull_x = self.anchor_x
        self.pull_y = self.anchor_y
        # Monotonic projectile id counter (see _Projectile.id).
        self._next_id = 0
        # Fixed-timestep integration state (see the SLING_PHYS_DT note).
        self._scale_idx = SLING_TIME_SCALES.index(1.0)
        self._time_acc = 0.0
        # Simulated time the current frame spans — contact impulses are
        # averaged over it so the force overlay reads in steady newtons.
        self._frame_sim_dt = SLING_FRAME_DT
        # Lumped quadratic-drag constant (1/2) rho Cd A in kg/m, from the
        # ball's real cross-section A = pi r^2.
        self._drag_k = (0.5 * SLING_AIR_DENSITY * SLING_DRAG_CD
                        * math.pi * self.r ** 2)

    @property
    def time_scale(self):
        """Current sim-speed multiplier (1.0 = real time)."""
        return SLING_TIME_SCALES[self._scale_idx]

    def speed_up(self):
        self._scale_idx = min(self._scale_idx + 1, len(SLING_TIME_SCALES) - 1)

    def speed_down(self):
        self._scale_idx = max(self._scale_idx - 1, 0)

    @property
    def grabbed(self):
        # Mirrors the interface UIManager uses for the black hole so the
        # onboarding pinch hint retires while the user is actively aiming.
        return self.aiming

    @staticmethod
    def _px(m):
        """Metres -> integer screen pixels."""
        return int(m * SLING_PX_PER_M)

    def _clamp_pull(self, mx_m, my_m):
        """Clamp the pulled ball position (metres) to the max pull radius."""
        max_pull = SLING_MAX_PULL_PX / SLING_PX_PER_M
        dx = mx_m - self.anchor_x
        dy = my_m - self.anchor_y
        dist = math.hypot(dx, dy)
        if dist > max_pull and dist > 0:
            scale = max_pull / dist
            dx *= scale
            dy *= scale
        return self.anchor_x + dx, self.anchor_y + dy

    def _launch_velocity(self):
        # Energy model: a pull of x metres stores E = 1/2 k x^2 in the band
        # and the ball leaves with KE = eff * E, i.e. v0 = x * sqrt(k*eff/m).
        # Fires opposite to the pull: pull down-left -> launches up-right.
        gain = math.sqrt(SLING_BAND_K * SLING_BAND_EFF / SLING_BALL_MASS)
        return (
            (self.anchor_x - self.pull_x) * gain,
            (self.anchor_y - self.pull_y) * gain,
        )

    def _fire(self):
        # Capture the launch point/velocity from the current pull BEFORE
        # resetting the aim back to the anchor.
        launch_x, launch_y = self.pull_x, self.pull_y
        vx, vy = self._launch_velocity()
        self.aiming = False
        self.aim_hand = None
        self.pull_x, self.pull_y = self.anchor_x, self.anchor_y
        # Ignore a dead-fire (pull too small to matter, < SLING_REST_SPEED m/s).
        if math.hypot(vx, vy) < SLING_REST_SPEED:
            return
        self.projectiles.append(
            _Projectile(launch_x, launch_y, vx, vy, self._next_id))
        self._next_id += 1
        if len(self.projectiles) > SLING_MAX_PROJECTILES:
            self.projectiles.pop(0)

    def update(self, hand_result, pose_landmarks):
        if self.aiming:
            # Owner latch: only the hand that started the aim may pull —
            # the other hand pinch-holding in the air must not yank the
            # shot to itself. The pinch machine outlives a short tracking
            # dropout (grace window, pull frozen); once the fingers open
            # — or the hand expires past the grace — `held` reads False
            # and the shot fires with the pull we had.
            _, held, (mx, my) = pinch_state(self.aim_hand)
            if held:
                # Convert the cursor to metres for the physics world.
                self.pull_x, self.pull_y = self._clamp_pull(
                    mx / SLING_PX_PER_M, my / SLING_PX_PER_M)
            else:
                self._fire()

        if not self.aiming and hand_result is not None:
            anchor_x_px = self.anchor_x * SLING_PX_PER_M
            anchor_y_px = self.anchor_y * SLING_PX_PER_M
            for i in range(len(hand_result.hand_landmarks)):
                hid = hand_id(hand_result, i)
                # The pinch cursor (mx, my) comes back in pixels.
                pinching, _, (mx, my) = pinch_state(hid)
                anchor_dist = math.hypot(anchor_x_px - mx, anchor_y_px - my)
                # Only a rapid close near the anchor starts an aim.
                if pinching and anchor_dist < SLING_GRAB_RADIUS_PX:
                    self.aim_hand = hid
                    self.pull_x, self.pull_y = self._clamp_pull(
                        mx / SLING_PX_PER_M, my / SLING_PX_PER_M)
                    self.aiming = True
                    break

        # Fade last frame's transient contact-force arrows (bounces / impacts).
        for p in self.projectiles:
            p.cfx *= SLING_CONTACT_DECAY
            p.cfy *= SLING_CONTACT_DECAY
        # Fixed-timestep advance: bank this frame's simulated time (scaled by
        # the sim-speed setting), then step the world in whole SLING_PHYS_DT
        # sub-steps. Trails are recorded last, after positions settle.
        self._frame_sim_dt = self.time_scale * SLING_FRAME_DT
        self._time_acc += self._frame_sim_dt
        steps = 0
        while self._time_acc >= SLING_PHYS_DT and steps < SLING_MAX_SUBSTEPS:
            self._time_acc -= SLING_PHYS_DT
            self._step_world(SLING_PHYS_DT)
            steps += 1
        if steps == SLING_MAX_SUBSTEPS:
            self._time_acc = 0.0
        for p in self.projectiles:
            if p.resting:
                # A ball parked on the floor: the steady normal reaction
                # exactly balances its weight (so the net force reads zero).
                p.cfx, p.cfy = 0.0, -SLING_BALL_MASS * SLING_G
            elif p.sliding:
                # A ball skidding along the floor: normal balances weight,
                # kinetic friction mu*m*g opposes the slide (so the net force
                # reads as pure friction — which is what decelerates it).
                fric = SLING_FRICTION_MU * SLING_BALL_MASS * SLING_G
                p.cfx = -math.copysign(fric, p.vx) if p.vx else 0.0
                p.cfy = -SLING_BALL_MASS * SLING_G
            p.trail.append((self._px(p.x), self._px(p.y)))

    def _step_world(self, dt):
        # Free-flight motion + walls first, then ball-vs-ball collisions so
        # every spawned ball obeys the same physics against the others.
        for p in self.projectiles:
            self._step(p, dt)
        self._resolve_collisions()

    def _accel(self, vx, vy):
        """Free-flight acceleration (m/s^2): gravity + quadratic air drag."""
        k = self._drag_k / SLING_BALL_MASS
        speed = math.hypot(vx, vy)
        return -k * speed * vx, SLING_G - k * speed * vy

    def _rk4_step(self, x, y, vx, vy, dt):
        """One classic 4th-order Runge-Kutta step of the free-flight ODE —
        the textbook integrator for projectile motion with velocity-dependent
        drag. Returns the new (x, y, vx, vy)."""
        ax1, ay1 = self._accel(vx, vy)
        vx2, vy2 = vx + ax1 * dt / 2, vy + ay1 * dt / 2
        ax2, ay2 = self._accel(vx2, vy2)
        vx3, vy3 = vx + ax2 * dt / 2, vy + ay2 * dt / 2
        ax3, ay3 = self._accel(vx3, vy3)
        vx4, vy4 = vx + ax3 * dt, vy + ay3 * dt
        ax4, ay4 = self._accel(vx4, vy4)
        nx = x + dt / 6 * (vx + 2 * vx2 + 2 * vx3 + vx4)
        ny = y + dt / 6 * (vy + 2 * vy2 + 2 * vy3 + vy4)
        nvx = vx + dt / 6 * (ax1 + 2 * ax2 + 2 * ax3 + ax4)
        nvy = vy + dt / 6 * (ay1 + 2 * ay2 + 2 * ay3 + ay4)
        return nx, ny, nvx, nvy

    def _step(self, p, dt):
        if p.resting:
            return
        m = SLING_BALL_MASS
        p.sliding = False
        p.x, p.y, p.vx, p.vy = self._rk4_step(p.x, p.y, p.vx, p.vy, dt)
        r = self.r
        # Contact impulses are reported as the average force over the frame's
        # simulated time, so the overlay reads in steady newtons.
        fdt = self._frame_sim_dt

        # Wall/floor bounces are impulse-based with a Coulomb friction cone:
        # the normal component reflects with restitution (normal impulse
        # jn = m(1+e)|vn|) and a friction impulse opposes the tangential
        # motion, capped at |jt| <= mu*|jn| (Coulomb's law).
        if p.x - r <= 0:
            p.x = r
            bvx, bvy = p.vx, p.vy
            jn = (1.0 + SLING_WALL_RESTITUTION) * abs(p.vx)
            jt = min(SLING_FRICTION_MU * jn, abs(p.vy))
            p.vx = abs(p.vx) * SLING_WALL_RESTITUTION
            p.vy -= math.copysign(jt, p.vy)
            p.cfx += m * (p.vx - bvx) / fdt
            p.cfy += m * (p.vy - bvy) / fdt
        elif p.x + r >= self.w:
            p.x = self.w - r
            bvx, bvy = p.vx, p.vy
            jn = (1.0 + SLING_WALL_RESTITUTION) * abs(p.vx)
            jt = min(SLING_FRICTION_MU * jn, abs(p.vy))
            p.vx = -abs(p.vx) * SLING_WALL_RESTITUTION
            p.vy -= math.copysign(jt, p.vy)
            p.cfx += m * (p.vx - bvx) / fdt
            p.cfy += m * (p.vy - bvy) / fdt

        if p.y - r <= 0:
            p.y = r
            bvx, bvy = p.vx, p.vy
            jn = (1.0 + SLING_WALL_RESTITUTION) * abs(p.vy)
            jt = min(SLING_FRICTION_MU * jn, abs(p.vx))
            p.vy = abs(p.vy) * SLING_WALL_RESTITUTION
            p.vx -= math.copysign(jt, p.vx)
            p.cfx += m * (p.vx - bvx) / fdt
            p.cfy += m * (p.vy - bvy) / fdt
        elif p.y + r >= self.h:
            p.y = self.h - r
            if p.vy > SLING_REST_SPEED:
                bvx, bvy = p.vx, p.vy
                jn = (1.0 + SLING_GROUND_RESTITUTION) * p.vy
                jt = min(SLING_FRICTION_MU * jn, abs(p.vx))
                p.vy = -p.vy * SLING_GROUND_RESTITUTION
                p.vx -= math.copysign(jt, p.vx)
                p.cfx += m * (p.vx - bvx) / fdt
                p.cfy += m * (p.vy - bvy) / fdt
            else:
                # Bounce energy spent -> grazing contact. The ball skids
                # along the floor under kinetic friction f = mu*m*g until it
                # stops. A resting ball skips integration until a collision
                # wakes it (see `_resolve_collisions`), so a pile can still
                # be knocked apart. (The steady contact force for both cases
                # is written in `update`, not accumulated here.)
                p.vy = 0.0
                decel = SLING_FRICTION_MU * SLING_G * dt
                p.vx -= math.copysign(min(decel, abs(p.vx)), p.vx)
                if abs(p.vx) < SLING_REST_SPEED:
                    p.vx = 0.0
                    p.resting = True
                else:
                    p.sliding = True

    def _resolve_collisions(self):
        """Equal-mass elastic collisions between every pair of balls (SI).

        Overlapping pairs are pushed apart (positional correction split evenly)
        and, when they are actually approaching, exchange their velocity
        component along the contact normal with `SLING_COLLISION_RESTITUTION`.
        The impulse is also recorded as a contact force (N) on both balls for
        the overlay. A real impact wakes resting balls; a gentle touch between
        two settled balls only separates them (no impulse) so a pile stays put.
        """
        r = self.r
        min_dist = 2 * r
        m = SLING_BALL_MASS
        n = len(self.projectiles)
        for a in range(n):
            pa = self.projectiles[a]
            for b in range(a + 1, n):
                pb = self.projectiles[b]
                dx = pb.x - pa.x
                dy = pb.y - pa.y
                dist = math.hypot(dx, dy)
                if dist >= min_dist:
                    continue
                if dist == 0.0:
                    # Perfectly coincident: separate along a fixed axis.
                    dx, dy, dist = 1.0, 0.0, 1.0
                nx, ny = dx / dist, dy / dist
                overlap = min_dist - dist
                pa.x -= nx * overlap * 0.5
                pa.y -= ny * overlap * 0.5
                pb.x += nx * overlap * 0.5
                pb.y += ny * overlap * 0.5

                # Relative velocity along the normal; > 0 means approaching.
                vrel = (pa.vx - pb.vx) * nx + (pa.vy - pb.vy) * ny
                if vrel > SLING_REST_SPEED:
                    j = (1.0 + SLING_COLLISION_RESTITUTION) * vrel * 0.5
                    pa.vx -= j * nx
                    pa.vy -= j * ny
                    pb.vx += j * nx
                    pb.vy += j * ny
                    # Impulse (m*j) as an average force over the frame's
                    # simulated time (matches the wall/floor reporting).
                    f = m * j / self._frame_sim_dt
                    pa.cfx -= f * nx
                    pa.cfy -= f * ny
                    pb.cfx += f * nx
                    pb.cfy += f * ny
                    pa.resting = pb.resting = False

        # Positional correction can shove a ball past an edge — clamp back in.
        for p in self.projectiles:
            p.x = min(max(p.x, r), self.w - r)
            p.y = min(max(p.y, r), self.h - r)

    def to_state(self):
        """Serializable snapshot for the web frontend.

        Everything the browser needs to redraw the slingshot this frame:
        the sim cannot be recomputed client-side (RK4 + collisions live
        here), so resolved positions and forces travel. Trails are NOT
        streamed — the stable projectile ids let the client accumulate one
        point per frame per ball, which reconstructs the trail exactly.
        """
        state = {
            "type": "slingshot",
            "anchor": [self._px(self.anchor_x), self._px(self.anchor_y)],
            "ball_r": SLING_RADIUS_PX,
            "aiming": self.aiming,
            "time_scale": self.time_scale,
            "pull": None,
            "readout": None,
            "arc": [],
            "projectiles": [],
        }
        if self.aiming:
            state["pull"] = [self._px(self.pull_x), self._px(self.pull_y)]
            angle, speed, force, e_band, ke = self._aim_readout()
            state["readout"] = {
                "angle": round(angle, 1), "v0": round(speed, 2),
                "draw_n": round(force, 1), "e_j": round(e_band, 1),
                "ke_j": round(ke, 1),
            }
            state["arc"] = [[x, y] for x, y in self._predicted_arc()]
        m = SLING_BALL_MASS
        for p in self.projectiles:
            speed = math.hypot(p.vx, p.vy)
            state["projectiles"].append({
                "id": p.id,
                "x": self._px(p.x), "y": self._px(p.y),
                "resting": p.resting, "sliding": p.sliding,
                # Live forces in newtons: weight, quadratic drag, contact.
                # The client scales them to px with the same constants and
                # sums them for the net arrow.
                "f_w": [0.0, round(m * SLING_G, 3)],
                "f_d": [round(-self._drag_k * speed * p.vx, 3),
                        round(-self._drag_k * speed * p.vy, 3)],
                "f_c": [round(p.cfx, 3), round(p.cfy, 3)],
            })
        return state

    def _predicted_arc(self):
        """Forward-simulate the pending shot for the dotted preview using the
        exact same integrator and timestep as the live physics, so the arc
        matches the real flight."""
        vx, vy = self._launch_velocity()
        x, y = self.pull_x, self.pull_y
        r = self.r
        pts = []
        for i in range(int(SLING_PREDICT_TIME_S / SLING_PHYS_DT)):
            x, y, vx, vy = self._rk4_step(x, y, vx, vy, SLING_PHYS_DT)
            if i % SLING_PREDICT_SAMPLE == 0:
                pts.append((self._px(x), self._px(y)))
            if x - r <= 0 or x + r >= self.w or y + r >= self.h:
                break
        return pts

    def _aim_readout(self):
        """Aim HUD numbers for the pending shot: launch angle (deg from the
        horizontal, 0 = right, +90 = straight up), launch speed (m/s), the
        band's Hooke draw force F = k x (N), the elastic energy it stores
        E = 1/2 k x^2 (J) and the KE actually delivered (= eff * E, J)."""
        vx, vy = self._launch_velocity()
        speed = math.hypot(vx, vy)                    # m/s
        pull = math.hypot(self.pull_x - self.anchor_x,
                          self.pull_y - self.anchor_y)  # draw length x (m)
        force = SLING_BAND_K * pull                   # N
        e_band = 0.5 * SLING_BAND_K * pull * pull     # J stored in the band
        ke = 0.5 * SLING_BALL_MASS * speed * speed    # J delivered (eff * E)
        # Screen y grows downward, so negate vy to make "up" a positive angle.
        angle = math.degrees(math.atan2(-vy, vx))
        return angle, speed, force, e_band, ke

    def _draw_readout(self, frame, angle, speed, force, e_band, ke):
        """Translucent SI readout above the anchor: launch angle/speed plus
        the band's draw force and its stored vs. delivered energy."""
        lines = [
            f"ANGLE {angle:+.0f} deg   v0 {speed:.1f} m/s",
            f"DRAW {force:.0f} N   E {e_band:.0f} J -> KE {ke:.0f} J",
        ]
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale, thick, pad = 0.6, 2, 8
        sizes = [cv2.getTextSize(t, font, scale, thick) for t in lines]
        line_h = max(th + base for (_, th), base in sizes) + 4
        box_w = max(tw for (tw, _), _ in sizes) + pad * 2
        box_h = line_h * len(lines) + pad * 2 - 4
        box_x = int(self.anchor_x * SLING_PX_PER_M - box_w / 2)
        box_x = max(0, min(box_x, self.w_px - box_w))  # keep on-screen
        box_y = max(0, int(self.anchor_y * SLING_PX_PER_M
                           - SLING_RADIUS_PX - 24 - box_h))

        overlay = frame.copy()
        cv2.rectangle(overlay, (box_x, box_y), (box_x + box_w, box_y + box_h),
                      (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)
        ty = box_y + pad
        for text, ((_, th), _) in zip(lines, sizes):
            ty += th
            cv2.putText(frame, text, (box_x + pad, ty), font, scale,
                        (0, 255, 255), thick, cv2.LINE_AA)
            ty += line_h - th

    @staticmethod
    def _draw_force_arrow(frame, cx, cy, fx, fy, color, tag=None, dashed=False):
        """Draw one force vector (newtons) as an outlined arrow, scaled to px.

        The arrow starts at the ball's edge (not its centre, so it never
        covers the ball), its length is capped so a bounce impulse cannot
        span the screen, and the head is a fixed-size filled triangle —
        `cv2.arrowedLine`'s proportional tip looks stubby on short arrows
        and bloated on long ones. `tag` letters the tip so each arrow reads
        without cross-referencing the legend; `dashed` styles the net-force
        arrow so it stays visible when it coincides with a single component
        (in free fall the net force IS the weight).
        """
        mag = math.hypot(fx, fy)
        if mag < SLING_MIN_FORCE_DRAW_N:
            return
        length = min(mag * SLING_FORCE_PX_PER_N, SLING_FORCE_MAX_PX)
        length = max(length, SLING_ARROW_HEAD_PX + 4)
        ux, uy = fx / mag, fy / mag
        sx = cx + ux * (SLING_RADIUS_PX + 3)
        sy = cy + uy * (SLING_RADIUS_PX + 3)
        ex, ey = sx + ux * length, sy + uy * length
        # Shaft stops where the head begins so the tip stays sharp.
        hx, hy = ex - ux * SLING_ARROW_HEAD_PX, ey - uy * SLING_ARROW_HEAD_PX
        wx, wy = -uy * SLING_ARROW_HEAD_PX * 0.55, ux * SLING_ARROW_HEAD_PX * 0.55
        head = np.array([
            (int(ex), int(ey)),
            (int(hx + wx), int(hy + wy)),
            (int(hx - wx), int(hy - wy)),
        ], dtype=np.int32)
        if dashed:
            # Shaft as short dashes (dash+gap ~ 9 px, dash fills 55% of it).
            shaft = math.hypot(hx - sx, hy - sy)
            n = max(2, int(shaft / 9))
            segs = []
            for i in range(n):
                t0 = i / n
                t1 = t0 + 0.55 / n
                segs.append((
                    (int(sx + (hx - sx) * t0), int(sy + (hy - sy) * t0)),
                    (int(sx + (hx - sx) * t1), int(sy + (hy - sy) * t1)),
                ))
        else:
            segs = [((int(sx), int(sy)), (int(hx), int(hy)))]
        # Dark under-stroke keeps the colours readable on any video content.
        for p0, p1 in segs:
            cv2.line(frame, p0, p1, (25, 25, 25), 5, cv2.LINE_AA)
        cv2.polylines(frame, [head], True, (25, 25, 25), 3, cv2.LINE_AA)
        for p0, p1 in segs:
            cv2.line(frame, p0, p1, color, 2, cv2.LINE_AA)
        cv2.fillPoly(frame, [head], color, cv2.LINE_AA)
        if tag:
            (tw, th), _ = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 2)
            # Centre the tag just past the tip, along the arrow direction.
            # The dashed net arrow often coincides with a component (free
            # fall: net = W), so its tag sits further out to avoid stacking.
            off = 24 if dashed else 8
            tx = int(ex + ux * (off + tw / 2) - tw / 2)
            ty = int(ey + uy * (off + th / 2) + th / 2)
            cv2.putText(frame, tag, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                        (25, 25, 25), 3, cv2.LINE_AA)
            cv2.putText(frame, tag, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                        color, 1, cv2.LINE_AA)

    def _draw_legend(self, frame):
        """Colour key for the force overlay + the SI constants in play.

        The box is sized from the measured text extents, so no row can
        overflow it regardless of the constants' formatting.
        """
        font = cv2.FONT_HERSHEY_SIMPLEX
        rows = [
            (SLING_COL_WEIGHT, "W  weight  m g"),
            (SLING_COL_DRAG, "D  air drag  1/2 rho Cd A v^2"),
            (SLING_COL_NORMAL, "N  contact  normal + friction"),
            (SLING_COL_NET, "net  sum of forces (dashed)"),
        ]
        # Terminal velocity sqrt(m g / k) — where drag balances weight.
        vt = math.sqrt(SLING_BALL_MASS * SLING_G / self._drag_k)
        footer = [
            f"g {SLING_G} m/s2   m {SLING_BALL_MASS:.1f} kg   r {self.r:.2f} m",
            f"Cd {SLING_DRAG_CD}   rho {SLING_AIR_DENSITY} kg/m3   vt {vt:.0f} m/s",
            f"band k {SLING_BAND_K} N/m   eff {SLING_BAND_EFF:.0%}   mu {SLING_FRICTION_MU}",
            f"RK4 @ {1.0 / SLING_PHYS_DT:.0f} Hz fixed step",
        ]
        row_scale, foot_scale = 0.45, 0.38
        text_x = 42          # rows: swatch line from x+10 to x+34, text after
        pad, line_h = 10, 22
        widths = [text_x + cv2.getTextSize(t, font, row_scale, 1)[0][0]
                  for _, t in rows]
        widths += [pad + cv2.getTextSize(t, font, foot_scale, 1)[0][0]
                   for t in footer]
        x, y = 20, 84
        box_w = max(widths) + pad
        box_h = line_h * (len(rows) + len(footer)) + 14
        overlay = frame.copy()
        cv2.rectangle(overlay, (x, y), (x + box_w, y + box_h), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)
        cy = y + 8
        for color, text in rows:
            cy += line_h
            cv2.line(frame, (x + 10, cy - 5), (x + 34, cy - 5), color, 3, cv2.LINE_AA)
            cv2.putText(frame, text, (x + text_x, cy), font, row_scale,
                        (230, 230, 230), 1, cv2.LINE_AA)
        for text in footer:
            cy += line_h
            cv2.putText(frame, text, (x + pad, cy), font, foot_scale,
                        (180, 180, 180), 1, cv2.LINE_AA)

    def draw(self, frame):
        self._draw_legend(frame)
        ax = int(self.anchor_x * SLING_PX_PER_M)
        ay = int(self.anchor_y * SLING_PX_PER_M)
        cv2.circle(frame, (ax, ay), 6, (180, 180, 180), -1)  # fixed anchor post

        if self.aiming:
            px = int(self.pull_x * SLING_PX_PER_M)
            py = int(self.pull_y * SLING_PX_PER_M)
            # Rubber band from the two forks of the anchor to the pulled ball.
            cv2.line(frame, (ax - 16, ay - 10), (px, py), (60, 200, 255), 3, cv2.LINE_AA)
            cv2.line(frame, (ax + 16, ay - 10), (px, py), (60, 200, 255), 3, cv2.LINE_AA)
            for tx, ty in self._predicted_arc():
                cv2.circle(frame, (tx, ty), 3, (0, 255, 255), -1)
            cv2.circle(frame, (px, py), SLING_RADIUS_PX, (0, 140, 255), -1)
            cv2.circle(frame, (px, py), SLING_RADIUS_PX, (255, 255, 255), 2, cv2.LINE_AA)
            self._draw_readout(frame, *self._aim_readout())
        else:
            # Idle ball ready to grab, resting above the anchor.
            cv2.circle(frame, (ax, ay - SLING_RADIUS_PX),
                       SLING_RADIUS_PX, (0, 140, 255), -1)

        m = SLING_BALL_MASS
        for p in self.projectiles:
            cx, cy = self._px(p.x), self._px(p.y)
            # Fading motion trail.
            n = len(p.trail)
            for i, (tx, ty) in enumerate(p.trail):
                t = (i + 1) / n if n else 0.0
                col = (int(60 * t), int(160 * t), int(255 * t))
                cv2.circle(frame, (tx, ty), max(1, int(SLING_RADIUS_PX * 0.3 * t)), col, -1)
            # The ball.
            cv2.circle(frame, (cx, cy), SLING_RADIUS_PX, (0, 90, 220), -1)
            cv2.circle(frame, (cx - SLING_RADIUS_PX // 4, cy - SLING_RADIUS_PX // 4),
                       SLING_RADIUS_PX // 4, (120, 210, 255), -1)
            # Force vectors acting on it right now (all in newtons): weight,
            # quadratic drag, the contact reaction, and their sum (net).
            speed = math.hypot(p.vx, p.vy)
            weight = (0.0, m * SLING_G)
            drag = (-self._drag_k * speed * p.vx, -self._drag_k * speed * p.vy)
            contact = (p.cfx, p.cfy)
            self._draw_force_arrow(frame, cx, cy, *weight, SLING_COL_WEIGHT,
                                   tag="W")
            self._draw_force_arrow(frame, cx, cy, *drag, SLING_COL_DRAG,
                                   tag="D")
            self._draw_force_arrow(frame, cx, cy, *contact, SLING_COL_NORMAL,
                                   tag="N")
            net = (weight[0] + drag[0] + contact[0],
                   weight[1] + drag[1] + contact[1])
            self._draw_force_arrow(frame, cx, cy, *net, SLING_COL_NET,
                                   tag="net", dashed=True)
