import math
import random
import time
from collections import deque

import cv2
import numpy as np

from config import (BH_DEFAULT_POS_FACTOR, BH_DISK_BRIGHTNESS,
                    BH_DISK_INNER_FACTOR, BH_DISK_OUTER_FACTOR,
                    BH_DISK_ROTATION_SPEED, BH_DISK_TILT_RAD,
                    BH_EINSTEIN_RADIUS_PX, BH_GRAB_RADIUS, ORB_BODY_TYPES,
                    ORB_COLLISION_SLOP, ORB_DEFAULT_KIND, ORB_FLASH_DECAY,
                    ORB_FRAG_COUNT, ORB_FRAG_LR_FRACTION, ORB_FRAG_MIN_MASS,
                    ORB_FRAG_SPEED, ORB_FRAG_VESC_FACTOR, ORB_FRAME_DT, ORB_G,
                    ORB_GRAB_PAD_PX, ORB_LAUNCH_GAIN, ORB_MAX_BODIES,
                    ORB_MAX_PULL_PX, ORB_MAX_SUBSTEPS, ORB_PHYS_DT,
                    ORB_PREDICT_SAMPLE, ORB_PREDICT_TIME_S, ORB_PRUNE_MARGIN,
                    ORB_RESTITUTION, ORB_SOFTENING_PX, ORB_TIME_SCALES,
                    ORB_TRAIL_LEN, PUPPET_IDLE_BOB_S, SIXSEVEN_FLASH_FRAMES,
                    SIXSEVEN_HYSTERESIS, SIXSEVEN_MIN_VISIBILITY, WAVE_AMP,
                    WAVE_DECAY_TAU_S, WAVE_DEFAULT_KIND, WAVE_FRAME_DT,
                    WAVE_GRAB_PAD_PX, WAVE_GRID_PX, WAVE_MAX_SOURCES,
                    WAVE_RAMP_S, WAVE_SOURCE_TYPES, WAVE_SPEED_PX_S,
                    WAVE_TIME_SCALES)
from detection.gestures import hand_id, pinch_info, pinch_state
from ui.button import Button

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


# --- Orbitals experiment (n-body gravity sandbox) -----------------------
# See the ORB_* block in config.py for the physics constants and the design
# rationale (symplectic velocity-Verlet, Plummer softening, screen-pixel
# units). Everything below runs in pixels / seconds.


def _radius_for_mass(mass):
    """Screen radius (px) for a body of the given mass — a cube-root (constant
    density) law clamped to a sane band, so a fused giant stays on-screen and a
    debris speck stays visible."""
    return int(max(3, min(46, 4.4 * (abs(mass) ** (1.0 / 3.0)))))


class _Body:
    __slots__ = ("id", "x", "y", "vx", "vy", "mass", "radius", "kind", "rgb",
                 "frozen", "ax", "ay", "trail", "flash")

    def __init__(self, bid, x, y, vx, vy, mass, radius, kind, rgb):
        self.id = bid
        self.x = x         # position (px)
        self.y = y
        self.vx = vx       # velocity (px/s)
        self.vy = vy
        self.mass = mass
        self.radius = radius
        self.kind = kind
        self.rgb = rgb     # (r, g, b) 0-255
        # Frozen while grabbed: still a gravity SOURCE and a collision wall,
        # but the integrator leaves its position/velocity to the hand.
        self.frozen = False
        self.ax = 0.0      # cached acceleration between Verlet half-steps
        self.ay = 0.0
        # Server-side trail for the cv2 path; the web path re-accumulates it
        # client-side from the streamed positions (one point per frame).
        self.trail = deque(maxlen=ORB_TRAIL_LEN)
        # Transient impact/merge glow (1 -> 0), rendered as an expanding ring.
        self.flash = 0.0


class Orbitals:
    """Newtonian n-body gravity sandbox driven by pinch gestures.

    Place bodies (star / planet / moon / comet, chosen from a palette) and
    watch them orbit, slingshot and merge. A pinch on empty space begins a
    slingshot-style aim: the spawn point is pinned where the fingers closed,
    the hand pulls back and a dotted arc (forward-simulated in the *live*
    gravity field) previews the orbit; releasing launches the body opposite
    the pull. A pinch on an existing body grabs it — drag to reposition, and
    the release velocity is imparted so you can fling planets into orbit. A
    grabbed body keeps pulling on the others (it is a fixed gravity source
    while held). Presets (Solar / Binary / Figure-8) drop a whole
    configuration in one press.

    Physics runs in screen pixels / seconds: symplectic velocity-Verlet at a
    fixed ``ORB_PHYS_DT`` sub-step (so ``time_scale`` — shared with the
    slingshot's -/+ stepper — never changes the step size), Plummer softening
    so close passes don't explode, and perfectly-inelastic merges that
    conserve mass and momentum. A merger past ``ORB_COLLAPSE_MASS`` collapses
    into a black hole (rendered as a dark disk + accretion ring).
    """

    def __init__(self, frame_width, frame_height):
        self.w = frame_width
        self.h = frame_height
        self.bodies = []
        self._next_id = 0
        self._kind = ORB_DEFAULT_KIND
        # Aim (place-with-velocity) state, mirroring the slingshot.
        self.aiming = False
        self.aim_hand = None
        self.spawn_x = 0.0
        self.spawn_y = 0.0
        self.pull_x = 0.0
        self.pull_y = 0.0
        # Grab (reposition/fling) state, mirroring BouncingSphere.
        self.grab_body = None
        self.grab_hand = None
        self.grab_offset_x = 0.0
        self.grab_offset_y = 0.0
        self._grab_prev = None    # last grabbed cursor, for release velocity
        # Fixed-timestep integration state (see the slingshot note).
        self._scale_idx = ORB_TIME_SCALES.index(1.0)
        self._time_acc = 0.0
        self._eps2 = ORB_SOFTENING_PX * ORB_SOFTENING_PX
        # Body-type palette + preset buttons, laid out top-left. Each type
        # button carries `selected` so the active spawn kind is highlighted.
        self._build_palette()
        self._apply_selection()

    # ---- palette -------------------------------------------------------

    def _build_palette(self):
        margin = int(self.h * 0.12)
        bw, bh, gap = 116, 46, 8
        x0, y0 = margin, margin
        types = [("star", "Star"), ("planet", "Planet"),
                 ("moon", "Moon"), ("comet", "Comet")]
        self._type_btns = []
        for i, (kind, label) in enumerate(types):
            btn = Button(
                x=x0 + i * (bw + gap), y=y0, width=bw, height=bh,
                label=label, on_click=(lambda k=kind: self._select(k)),
                font_scale=0.6,
            )
            self._type_btns.append((f"orb.type.{kind}", kind, btn))

        y1 = y0 + bh + gap
        presets = [("solar", "Solar", self._preset_solar),
                   ("binary", "Binary", self._preset_binary),
                   ("figure8", "Figure 8", self._preset_figure8),
                   ("clear", "Clear", self.clear)]
        self._preset_btns = []
        for i, (pid, label, fn) in enumerate(presets):
            btn = Button(
                x=x0 + i * (bw + gap), y=y1, width=bw, height=bh,
                label=label, on_click=fn, font_scale=0.6,
            )
            self._preset_btns.append((f"orb.preset.{pid}", btn))

    @property
    def palette(self):
        """(id, Button) list the UIManager updates / draws / serializes —
        the experiment owns its own buttons so main.py stays thin."""
        return ([(bid, btn) for bid, _kind, btn in self._type_btns]
                + self._preset_btns)

    def _select(self, kind):
        self._kind = kind
        self._apply_selection()

    def _apply_selection(self):
        for _bid, kind, btn in self._type_btns:
            btn.selected = (kind == self._kind)

    # ---- sim-speed stepper (same interface as the slingshot) -----------

    @property
    def time_scale(self):
        return ORB_TIME_SCALES[self._scale_idx]

    def speed_up(self):
        self._scale_idx = min(self._scale_idx + 1, len(ORB_TIME_SCALES) - 1)

    def speed_down(self):
        self._scale_idx = max(self._scale_idx - 1, 0)

    @property
    def grabbed(self):
        # Retires the onboarding hint while actively placing or dragging.
        return self.aiming or self.grab_body is not None

    # ---- spawning / presets --------------------------------------------

    def _spawn(self, x, y, vx, vy, kind, mass=None, radius=None, rgb=None):
        spec = ORB_BODY_TYPES[kind]
        mass = spec["mass"] if mass is None else mass
        radius = spec["radius"] if radius is None else radius
        rgb = list(spec["rgb"]) if rgb is None else list(rgb)
        body = _Body(self._next_id, x, y, vx, vy, mass, radius, kind, rgb)
        self._next_id += 1
        self.bodies.append(body)
        if len(self.bodies) > ORB_MAX_BODIES:
            self.bodies.pop(0)
        return body

    def clear(self):
        self.bodies.clear()
        self.aiming = False
        self.aim_hand = None
        self.grab_body = None
        self.grab_hand = None

    def _circular_v(self, cx, cy, x, y, central_mass, sign=1.0):
        """Tangential speed for a circular orbit of a test body at (x, y)
        around a central mass at (cx, cy): v = sqrt(G M / r), perpendicular
        to the radius (sign picks the orbit direction)."""
        dx, dy = x - cx, y - cy
        r = math.hypot(dx, dy) or 1.0
        v = math.sqrt(ORB_G * central_mass / r)
        # Perpendicular to (dx, dy).
        return (-dy / r * v * sign, dx / r * v * sign)

    def _preset_solar(self):
        self.clear()
        cx, cy = self.w * 0.5, self.h * 0.5
        star = ORB_BODY_TYPES["star"]["mass"]
        self._spawn(cx, cy, 0.0, 0.0, "star")
        # Planets on progressively wider circular orbits, seeded at spread
        # starting angles so they don't all line up on one side. Their mass
        # is kept tiny (near test-particles) so mutual perturbation can't
        # slowly eject or merge them — the preset should read as a clean,
        # stable system (the sandbox is where heavy bodies interact).
        orbits = [(140, "planet", 0.0), (235, "planet", 2.3),
                  (330, "moon", 4.6)]
        for r, kind, ang in orbits:
            px, py = cx + r * math.cos(ang), cy + r * math.sin(ang)
            vx, vy = self._circular_v(cx, cy, px, py, star, sign=1.0)
            self._spawn(px, py, vx, vy, kind, mass=4.0)

    def _preset_binary(self):
        self.clear()
        cx, cy = self.w * 0.5, self.h * 0.5
        m = ORB_BODY_TYPES["star"]["mass"]
        d = 220.0                       # separation
        v = 0.5 * math.sqrt(ORB_G * (2 * m) / d)  # each star's orbital speed
        # Two equal stars waltzing about their common centre of mass. A
        # circumbinary planet close enough to stay on-screen sits inside the
        # binary's chaotic zone (it would be ejected), so the preset is just
        # the clean, indefinitely-stable two-star dance.
        self._spawn(cx - d / 2, cy, 0.0, -v, "star")
        self._spawn(cx + d / 2, cy, 0.0, v, "star")

    def _preset_figure8(self):
        """The Chenciner–Montgomery three-body choreography: three equal
        masses chasing each other along a single figure-eight. The canonical
        G=m=1 initial conditions are scaled to screen pixels (length scale L,
        derived velocity scale sqrt(G m / L)); screen-y grows downward, which
        just mirrors the eight vertically."""
        self.clear()
        cx, cy = self.w * 0.5, self.h * 0.5
        L = 230.0
        m = 240.0
        V = math.sqrt(ORB_G * m / L)
        r = 16
        x1, y1 = 0.97000436, -0.24308753
        v1x, v1y = 0.4662036850, 0.4323657300
        cols = [[255, 214, 120], [130, 200, 255], [235, 150, 220]]
        specs = [
            (x1, y1, v1x, v1y),
            (-x1, -y1, v1x, v1y),
            (0.0, 0.0, -2 * v1x, -2 * v1y),
        ]
        for (px, py, vx, vy), rgb in zip(specs, cols):
            self._spawn(cx + px * L, cy + py * L,
                        vx * V, vy * V, "star", mass=m, radius=r, rgb=rgb)

    # ---- interaction ---------------------------------------------------

    def _clamp_pull(self, mx, my):
        dx, dy = mx - self.spawn_x, my - self.spawn_y
        dist = math.hypot(dx, dy)
        if dist > ORB_MAX_PULL_PX and dist > 0:
            s = ORB_MAX_PULL_PX / dist
            dx, dy = dx * s, dy * s
        return self.spawn_x + dx, self.spawn_y + dy

    def _launch_velocity(self):
        # Fires opposite the pull, like the slingshot.
        return ((self.spawn_x - self.pull_x) * ORB_LAUNCH_GAIN,
                (self.spawn_y - self.pull_y) * ORB_LAUNCH_GAIN)

    def _fire(self):
        vx, vy = self._launch_velocity()
        sx, sy = self.spawn_x, self.spawn_y
        self.aiming = False
        self.aim_hand = None
        self._spawn(sx, sy, vx, vy, self._kind)

    def _body_at(self, px, py):
        """The nearest body whose disk (plus a small pad) contains (px, py),
        or None — used to disambiguate grab-a-body from place-a-new-one."""
        best, best_d = None, None
        for b in self.bodies:
            d = math.hypot(b.x - px, b.y - py)
            if d <= b.radius + ORB_GRAB_PAD_PX and (best_d is None or d < best_d):
                best, best_d = b, d
        return best

    def update(self, hand_result, pose_landmarks):
        # 1) Continue an in-progress grab or aim (owner-latched, like the
        #    slingshot / sphere): the pinch machine outlives a brief tracking
        #    dropout, and the gesture ends when the fingers open.
        if self.grab_body is not None:
            _, held, (mx, my) = pinch_state(self.grab_hand)
            if held and self.grab_body in self.bodies:
                nx = mx + self.grab_offset_x
                ny = my + self.grab_offset_y
                if self._grab_prev is not None:
                    px, py = self._grab_prev
                    self.grab_body.vx = (nx - px) / ORB_FRAME_DT
                    self.grab_body.vy = (ny - py) / ORB_FRAME_DT
                self.grab_body.x, self.grab_body.y = nx, ny
                self._grab_prev = (nx, ny)
            else:
                if self.grab_body in self.bodies:
                    self.grab_body.frozen = False
                self.grab_body = None
                self.grab_hand = None
                self._grab_prev = None

        if self.aiming:
            _, held, (mx, my) = pinch_state(self.aim_hand)
            if held:
                self.pull_x, self.pull_y = self._clamp_pull(mx, my)
            else:
                self._fire()

        # 2) Start a new gesture on a fresh pinch: grab a body if the close
        #    landed on one, otherwise begin aiming a new body.
        if (not self.aiming and self.grab_body is None
                and hand_result is not None):
            for i in range(len(hand_result.hand_landmarks)):
                hid = hand_id(hand_result, i)
                pinching, _, (mx, my) = pinch_state(hid)
                if not pinching:
                    continue
                hit = self._body_at(mx, my)
                if hit is not None:
                    self.grab_body = hit
                    self.grab_hand = hid
                    self.grab_offset_x = hit.x - mx
                    self.grab_offset_y = hit.y - my
                    hit.frozen = True
                    self._grab_prev = (hit.x, hit.y)
                else:
                    self.aim_hand = hid
                    self.spawn_x, self.spawn_y = mx, my
                    self.pull_x, self.pull_y = mx, my
                    self.aiming = True
                break

        # 3) Advance the sim: bank this frame's simulated time (scaled by the
        #    sim-speed setting) and step in whole ORB_PHYS_DT sub-steps. The
        #    acceleration is seeded ONCE here for the whole substep loop; each
        #    _step then carries a(t+dt) forward as the next step's a(t), so the
        #    O(n^2) force sum runs once per step, not twice.
        self._time_acc += self.time_scale * ORB_FRAME_DT
        if self.bodies and self._time_acc >= ORB_PHYS_DT:
            self._accelerate()
        steps = 0
        while self._time_acc >= ORB_PHYS_DT and steps < ORB_MAX_SUBSTEPS:
            self._time_acc -= ORB_PHYS_DT
            self._step(ORB_PHYS_DT)
            steps += 1
        if steps == ORB_MAX_SUBSTEPS:
            self._time_acc = 0.0

        self._prune()
        for b in self.bodies:
            if b.flash > 0.0:
                b.flash = max(0.0, b.flash - ORB_FLASH_DECAY)
            b.trail.append((int(b.x), int(b.y)))

    def _accelerate(self):
        """Fill every body's (ax, ay) with the softened gravitational
        acceleration from all the others. Frozen (grabbed) bodies still act
        as sources; only their own motion is suppressed later."""
        bodies = self.bodies
        n = len(bodies)
        for b in bodies:
            b.ax = 0.0
            b.ay = 0.0
        eps2 = self._eps2
        G = ORB_G
        for i in range(n):
            bi = bodies[i]
            xi, yi = bi.x, bi.y
            for j in range(i + 1, n):
                bj = bodies[j]
                dx = bj.x - xi
                dy = bj.y - yi
                inv_r = 1.0 / ((dx * dx + dy * dy + eps2) ** 1.5)
                fi = G * bj.mass * inv_r
                fj = G * bi.mass * inv_r
                bi.ax += fi * dx
                bi.ay += fi * dy
                bj.ax -= fj * dx
                bj.ay -= fj * dy

    def _step(self, dt):
        """One symplectic velocity-Verlet (leapfrog) step, 2nd-order and
        energy-stable. Each body's (ax, ay) ENTERS holding a(current position)
        — seeded before the substep loop and carried from the previous step's
        recomputation — so the O(n^2) force sum is evaluated once per step
        (a(t+dt)), not twice."""
        if not self.bodies:
            return
        half = 0.5 * dt
        for b in self.bodies:
            if b.frozen:
                continue
            b.x += b.vx * dt + b.ax * half * dt   # drift with a(t)
            b.y += b.vy * dt + b.ay * half * dt
            b.vx += b.ax * half                   # half-kick with a(t)
            b.vy += b.ay * half
        self._accelerate()                        # a(t+dt) = next step's a(t)
        for b in self.bodies:
            if b.frozen:
                continue
            b.vx += b.ax * half                   # half-kick with a(t+dt)
            b.vy += b.ay * half
        # Collisions may merge/fragment (change the body list) — refresh the
        # cached accelerations so the next sub-step's drift is valid.
        if self._resolve_collisions():
            self._accelerate()

    def _resolve_collisions(self):
        """Decide each overlapping pair's OUTCOME by the impact speed vs the
        mutual escape velocity ``v_esc = sqrt(2 G M_tot / R_tot)`` — the
        Leinhardt & Stewart (2012) criterion used in real N-body codes:

            v_impact <= v_esc            -> MERGE (perfect accretion): fuse
                into one body, mass + momentum conserved, radius by volume.
            v_esc < v_impact <= FRAG*v_esc -> BOUNCE (hit-and-run): a
                hard-sphere restitution impulse deflects both by mass ratio.
            v_impact > FRAG*v_esc        -> FRAGMENT (catastrophic
                disruption): shatter into a largest remnant + debris that fly
                out conserving total mass + momentum (and gravitate again).

        Returns True if the body LIST changed (merge/fragment) so the caller
        can refresh cached accelerations. A grabbed (frozen) body only ever
        bounces — it must not fuse or shatter out of the user's hand.
        """
        bodies = self.bodies
        dead = set()
        born = []
        n = len(bodies)
        for i in range(n):
            a = bodies[i]
            if id(a) in dead:
                continue
            for k in range(i + 1, n):
                b = bodies[k]
                if id(b) in dead:
                    continue
                dx = b.x - a.x
                dy = b.y - a.y
                dist = math.hypot(dx, dy)
                min_dist = a.radius + b.radius
                if dist >= min_dist:
                    continue
                if dist > 1e-9:
                    nx, ny = dx / dist, dy / dist
                else:
                    nx, ny, dist = 1.0, 0.0, 0.0
                M = a.mass + b.mass
                v_esc = math.sqrt(2.0 * ORB_G * M / max(min_dist, 1e-6))
                v_imp = math.hypot(a.vx - b.vx, a.vy - b.vy)

                if a.frozen or b.frozen:
                    self._bounce(a, b, nx, ny, dist, min_dist)
                elif v_imp <= v_esc:
                    self._merge_pair(a, b)          # a becomes the fused body
                    dead.add(id(b))
                    break                            # a changed; next i
                elif (v_imp > ORB_FRAG_VESC_FACTOR * v_esc
                      and M > 2 * ORB_FRAG_MIN_MASS):
                    born.extend(self._fragment(a, b))
                    dead.add(id(a))
                    dead.add(id(b))
                    break
                else:
                    self._bounce(a, b, nx, ny, dist, min_dist)

        if dead or born:
            kept = [x for x in bodies if id(x) not in dead]
            self.bodies = (kept + born)[-ORB_MAX_BODIES:]
            return True
        return False

    def _bounce(self, a, b, nx, ny, dist, min_dist):
        """Hard-sphere restitution impulse + inverse-mass positional
        correction (the hit-and-run regime). Momentum conserved exactly."""
        inv_a = 0.0 if a.frozen else 1.0 / a.mass
        inv_b = 0.0 if b.frozen else 1.0 / b.mass
        inv_sum = inv_a + inv_b
        if inv_sum == 0.0:
            return
        vrel = (a.vx - b.vx) * nx + (a.vy - b.vy) * ny
        if vrel > 0.0:
            j = (1.0 + ORB_RESTITUTION) * vrel / inv_sum
            a.vx -= j * inv_a * nx
            a.vy -= j * inv_a * ny
            b.vx += j * inv_b * nx
            b.vy += j * inv_b * ny
            a.flash = max(a.flash, 0.5)
            b.flash = max(b.flash, 0.5)
        corr = max(min_dist - dist - ORB_COLLISION_SLOP, 0.0) / inv_sum
        a.x -= corr * inv_a * nx
        a.y -= corr * inv_a * ny
        b.x += corr * inv_b * nx
        b.y += corr * inv_b * ny

    def _merge_pair(self, a, b):
        """Fuse b into a (perfect accretion): a becomes the combined body,
        conserving mass + momentum, radius recombined by volume, colour blended
        by mass. b is dropped by the caller."""
        M = a.mass + b.mass
        a.x = (a.mass * a.x + b.mass * b.x) / M
        a.y = (a.mass * a.y + b.mass * b.y) / M
        a.vx = (a.mass * a.vx + b.mass * b.vx) / M
        a.vy = (a.mass * a.vy + b.mass * b.vy) / M
        a.rgb = [int((a.mass * a.rgb[c] + b.mass * b.rgb[c]) / M)
                 for c in range(3)]
        if b.mass > a.mass:
            a.kind = b.kind
        a.radius = _radius_for_mass(M)
        a.mass = M
        a.flash = 1.0

    def _fragment(self, a, b):
        """Catastrophic disruption: replace a + b with a largest remnant plus
        ``ORB_FRAG_COUNT`` debris. Total mass and momentum are conserved — the
        fragments' velocities are the centre-of-mass velocity plus an isotropic
        scatter whose mass-weighted mean is removed, so sum(m_i v_i) = the
        original momentum exactly. Fragments gravitate afterwards, so debris
        can re-accumulate."""
        M = a.mass + b.mass
        cx = (a.mass * a.x + b.mass * b.x) / M
        cy = (a.mass * a.y + b.mass * b.y) / M
        vcx = (a.mass * a.vx + b.mass * b.vx) / M
        vcy = (a.mass * a.vy + b.mass * b.vy) / M
        v_imp = math.hypot(a.vx - b.vx, a.vy - b.vy)
        scatter = ORB_FRAG_SPEED * v_imp
        rgb = [int((a.mass * a.rgb[c] + b.mass * b.rgb[c]) / M)
               for c in range(3)]
        kind_lr = a.kind if a.mass >= b.mass else b.kind

        lr_mass = M * ORB_FRAG_LR_FRACTION
        deb_mass = (M - lr_mass) / ORB_FRAG_COUNT
        masses = [lr_mass] + [deb_mass] * ORB_FRAG_COUNT
        # Isotropic scatter velocities (COM frame); the remnant barely moves.
        us = []
        for idx in range(len(masses)):
            ang = random.uniform(0.0, 2.0 * math.pi)
            sp = scatter * 0.12 if idx == 0 else scatter * (0.5 + random.random())
            us.append((math.cos(ang) * sp, math.sin(ang) * sp))
        mux = sum(masses[i] * us[i][0] for i in range(len(masses))) / M
        muy = sum(masses[i] * us[i][1] for i in range(len(masses))) / M

        r_sep = (a.radius + b.radius) * 0.6
        frags = []
        for i, m in enumerate(masses):
            ux = us[i][0] - mux            # momentum-conserving COM velocity
            uy = us[i][1] - muy
            sp = math.hypot(ux, uy) or 1.0
            r = _radius_for_mass(m)
            body = _Body(self._next_id,
                         cx + ux / sp * r_sep, cy + uy / sp * r_sep,
                         vcx + ux, vcy + uy, m, r,
                         kind_lr if i == 0 else "comet", list(rgb))
            body.flash = 1.0
            self._next_id += 1
            frags.append(body)
        return frags

    def _prune(self):
        """Drop bodies that have flung far off-screen so the body count and
        cost stay bounded (a grabbed body is never pruned)."""
        mx = self.w * ORB_PRUNE_MARGIN
        my = self.h * ORB_PRUNE_MARGIN
        kept = []
        for b in self.bodies:
            if b is self.grab_body or (-mx < b.x < mx and -my < b.y < my):
                kept.append(b)
        self.bodies = kept

    # ---- aim preview ---------------------------------------------------

    def _predicted_arc(self):
        """Forward-simulate the pending body through the CURRENT (held-fixed)
        gravity field for a short horizon, so the dotted preview matches the
        orbit it will actually fall into."""
        vx, vy = self._launch_velocity()
        x, y = self.spawn_x, self.spawn_y
        eps2 = self._eps2
        sources = [(b.x, b.y, b.mass) for b in self.bodies]
        pts = []
        steps = int(ORB_PREDICT_TIME_S / ORB_PHYS_DT)
        dt = ORB_PHYS_DT
        mx, my = self.w * ORB_PRUNE_MARGIN, self.h * ORB_PRUNE_MARGIN
        for i in range(steps):
            ax = ay = 0.0
            for sx, sy, sm in sources:
                dx, dy = sx - x, sy - y
                inv = ORB_G * sm / ((dx * dx + dy * dy + eps2) ** 1.5)
                ax += inv * dx
                ay += inv * dy
            vx += ax * dt
            vy += ay * dt
            x += vx * dt
            y += vy * dt
            if i % ORB_PREDICT_SAMPLE == 0:
                pts.append((int(x), int(y)))
            if not (-mx < x < mx and -my < y < my):
                break
        return pts

    # ---- serialization -------------------------------------------------

    def to_state(self):
        """Serializable snapshot for the web frontend. The sim is authoritative
        here (velocity-Verlet + merges cannot be recomputed client-side), so
        resolved positions travel; trails are re-accumulated client-side from
        the stable body ids, exactly like the slingshot's projectiles."""
        spec = ORB_BODY_TYPES[self._kind]
        state = {
            "type": "orbitals",
            "bodies": [{
                "id": b.id,
                "x": round(b.x, 1), "y": round(b.y, 1),
                "r": b.radius, "rgb": b.rgb, "kind": b.kind,
                "m": round(b.mass, 1),
                "flash": round(b.flash, 3),
            } for b in self.bodies],
            "count": len(self.bodies),
            "kind": self._kind,
            "kind_r": spec["radius"],
            "kind_rgb": list(spec["rgb"]),
            "kind_m": spec["mass"],
            "time_scale": self.time_scale,
            "aiming": self.aiming,
            "spawn": None,
            "pull": None,
            "arc": [],
            "readout": None,
        }
        if self.aiming:
            vx, vy = self._launch_velocity()
            speed = math.hypot(vx, vy)
            state["spawn"] = [round(self.spawn_x, 1), round(self.spawn_y, 1)]
            state["pull"] = [round(self.pull_x, 1), round(self.pull_y, 1)]
            state["arc"] = [[x, y] for x, y in self._predicted_arc()]
            state["readout"] = {
                "v0": round(speed, 1),
                "angle": round(math.degrees(math.atan2(-vy, vx)), 1),
                "kind": self._kind,
                "mass": spec["mass"],
            }
        return state

    # ---- cv2 drawing (window / stream fallback) ------------------------

    def _draw_body(self, frame, b):
        cx, cy = int(b.x), int(b.y)
        r, g, bl = b.rgb
        # A cheap glow: a dim outer halo, the body, and a bright core.
        cv2.circle(frame, (cx, cy), b.radius + 6,
                   (int(bl * 0.35), int(g * 0.35), int(r * 0.35)), -1, cv2.LINE_AA)
        cv2.circle(frame, (cx, cy), b.radius, (bl, g, r), -1, cv2.LINE_AA)
        cv2.circle(frame, (cx - b.radius // 4, cy - b.radius // 4),
                   max(2, b.radius // 3),
                   (min(255, bl + 60), min(255, g + 60), min(255, r + 60)),
                   -1, cv2.LINE_AA)
        # Impact / merge flash: an expanding white ring that fades out.
        if b.flash > 0.0:
            fr = int(b.radius + (1.0 - b.flash) * b.radius * 3.0)
            cv2.circle(frame, (cx, cy), fr, (255, 255, 255),
                       max(1, int(b.flash * 3)), cv2.LINE_AA)

    def draw(self, frame):
        # Trails (fading toward the body's colour).
        for b in self.bodies:
            n = len(b.trail)
            r, g, bl = b.rgb
            for i, (tx, ty) in enumerate(b.trail):
                t = (i + 1) / n if n else 0.0
                cv2.circle(frame, (tx, ty),
                           max(1, int(b.radius * 0.28 * t)),
                           (int(bl * t), int(g * t), int(r * t)), -1)
        for b in self.bodies:
            self._draw_body(frame, b)

        if self.aiming:
            sx, sy = int(self.spawn_x), int(self.spawn_y)
            px, py = int(self.pull_x), int(self.pull_y)
            spec = ORB_BODY_TYPES[self._kind]
            r, g, bl = spec["rgb"]
            cv2.line(frame, (sx, sy), (px, py), (200, 200, 200), 2, cv2.LINE_AA)
            for tx, ty in self._predicted_arc():
                cv2.circle(frame, (tx, ty), 2, (bl, g, r), -1)
            # Ghost of the body to be launched + a velocity vector.
            cv2.circle(frame, (sx, sy), spec["radius"], (bl, g, r), 2, cv2.LINE_AA)
            vx, vy = self._launch_velocity()
            mag = math.hypot(vx, vy)
            if mag > 1:
                ex = int(sx + vx / mag * min(mag * 0.25, 140))
                ey = int(sy + vy / mag * min(mag * 0.25, 140))
                cv2.arrowedLine(frame, (sx, sy), (ex, ey), (bl, g, r), 2,
                                cv2.LINE_AA, tipLength=0.25)
            cv2.putText(frame, f"{self._kind}  v0 {mag:.0f} px/s",
                        (sx + 12, sy - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                        (240, 240, 240), 2, cv2.LINE_AA)


# --- Waves experiment (interactive ripple tank) ---------------------------


class _WaveSource:
    __slots__ = ("id", "x", "y", "kind", "freq", "born")

    def __init__(self, sid, x, y, kind, freq, born):
        self.id = sid
        self.x = x
        self.y = y
        self.kind = kind
        self.freq = freq   # oscillation frequency (Hz)
        self.born = born   # experiment-clock time the source appeared (s)


class Waves:
    """Interactive ripple tank: point sources on a 2D wave-equation field.

    A pinch on empty water drops an oscillating source of the palette's
    selected frequency; a pinch on an existing source grabs it — dragging a
    live source compresses its wake ahead and stretches it behind (a real
    Doppler pattern), and two or more sources paint a standing interference
    pattern. Screen edges reflect like tank walls.

    This class owns the SOURCES only (placement, dragging, palette, the
    experiment clock) — all the logic. The field itself is presentation and
    lives with whichever sink renders it: the browser integrates the wave
    equation in a WebGL ping-pong texture (web/src/gl/WavesLayer.tsx); the
    cv2 window/stream fallback runs the same damped finite-difference
    scheme in numpy at ``WAVE_GRID_PX`` resolution (in :meth:`draw`, so web
    mode never pays for it). The -/+ sim-speed stepper scales the clock,
    which both renderers follow, so it speeds oscillation and propagation
    together.
    """

    def __init__(self, frame_width, frame_height):
        self.w = frame_width
        self.h = frame_height
        self.sources = []
        self._next_id = 0
        self._kind = WAVE_DEFAULT_KIND
        self._clock = 0.0
        self._scale_idx = WAVE_TIME_SCALES.index(1.0)
        # Grab (drag a source) state, mirroring the Orbitals grab.
        self.grab_src = None
        self.grab_hand = None
        self.grab_offset_x = 0.0
        self.grab_offset_y = 0.0
        # cv2-fallback field state, lazily built on first draw() call.
        self._u = None          # field at t (float32, grid res)
        self._u_prev = None     # field at t - dt
        self._field_t = 0.0     # how far the field has been integrated
        self._build_palette()
        self._apply_selection()

    # ---- palette -------------------------------------------------------

    def _build_palette(self):
        margin = int(self.h * 0.12)
        bw, bh, gap = 116, 46, 8
        x0, y0 = margin, margin
        self._freq_btns = []
        for i, (kind, spec) in enumerate(WAVE_SOURCE_TYPES.items()):
            btn = Button(
                x=x0 + i * (bw + gap), y=y0, width=bw, height=bh,
                label=spec["label"], on_click=(lambda k=kind: self._select(k)),
                font_scale=0.6,
            )
            self._freq_btns.append((f"wave.freq.{kind}", kind, btn))
        self._clear_btn = Button(
            x=x0 + len(self._freq_btns) * (bw + gap), y=y0, width=bw, height=bh,
            label="Clear", on_click=self.clear, font_scale=0.6,
        )

    @property
    def palette(self):
        """(id, Button) list the UIManager updates / draws / serializes."""
        return ([(bid, btn) for bid, _kind, btn in self._freq_btns]
                + [("wave.clear", self._clear_btn)])

    def _select(self, kind):
        self._kind = kind
        self._apply_selection()

    def _apply_selection(self):
        for _bid, kind, btn in self._freq_btns:
            btn.selected = (kind == self._kind)

    # ---- sim-speed stepper (same interface as the slingshot) -----------

    @property
    def time_scale(self):
        return WAVE_TIME_SCALES[self._scale_idx]

    def speed_up(self):
        self._scale_idx = min(self._scale_idx + 1, len(WAVE_TIME_SCALES) - 1)

    def speed_down(self):
        self._scale_idx = max(self._scale_idx - 1, 0)

    @property
    def grabbed(self):
        # Retires the onboarding hint while dragging a source.
        return self.grab_src is not None

    # ---- interaction ---------------------------------------------------

    def clear(self):
        """Drop every source. The field is NOT zeroed — the last ripples
        ring down naturally in both renderers, like a real tank."""
        self.sources.clear()
        self.grab_src = None
        self.grab_hand = None

    def _place(self, x, y):
        spec = WAVE_SOURCE_TYPES[self._kind]
        src = _WaveSource(self._next_id, x, y, self._kind, spec["freq"],
                          self._clock)
        self._next_id += 1
        self.sources.append(src)
        # Hard cap (it is also the shader's uniform array size): the oldest
        # source gives way.
        if len(self.sources) > WAVE_MAX_SOURCES:
            self.sources.pop(0)

    def _source_at(self, px, py):
        best, best_d = None, None
        for s in self.sources:
            d = math.hypot(s.x - px, s.y - py)
            if d <= WAVE_GRAB_PAD_PX and (best_d is None or d < best_d):
                best, best_d = s, d
        return best

    def update(self, hand_result, pose_landmarks):
        # 1) Continue an in-progress drag (owner-latched: the pinch machine
        #    outlives a brief tracking dropout; the drag ends on release).
        if self.grab_src is not None:
            _, held, (mx, my) = pinch_state(self.grab_hand)
            if held and self.grab_src in self.sources:
                self.grab_src.x = mx + self.grab_offset_x
                self.grab_src.y = my + self.grab_offset_y
            else:
                self.grab_src = None
                self.grab_hand = None

        # 2) A fresh pinch grabs the source it landed on, or drops a new one.
        if self.grab_src is None and hand_result is not None:
            for i in range(len(hand_result.hand_landmarks)):
                hid = hand_id(hand_result, i)
                pinching, _, (mx, my) = pinch_state(hid)
                if not pinching:
                    continue
                hit = self._source_at(mx, my)
                if hit is not None:
                    self.grab_src = hit
                    self.grab_hand = hid
                    self.grab_offset_x = hit.x - mx
                    self.grab_offset_y = hit.y - my
                else:
                    self._place(mx, my)
                break

        # 3) Advance the experiment clock (the renderers' time base).
        self._clock += self.time_scale * WAVE_FRAME_DT

    # ---- serialization --------------------------------------------------

    def to_state(self):
        return {
            "type": "waves",
            "t": round(self._clock, 3),
            "c": WAVE_SPEED_PX_S,
            "time_scale": self.time_scale,
            "kind": self._kind,
            "count": len(self.sources),
            "sources": [{
                "id": s.id,
                "x": round(s.x, 1),
                "y": round(s.y, 1),
                "freq": s.freq,
                "amp": WAVE_AMP,
                "born": round(s.born, 3),
                "grabbed": s is self.grab_src,
            } for s in self.sources],
        }

    # ---- cv2 drawing (window / stream fallback) ------------------------
    #
    # The same damped 2D wave equation the WebGL layer integrates, on a
    # coarse numpy grid:  u_next = (2-d)u - (1-d)u_prev + s^2 * lap(u), with
    # sources blended in as Dirichlet oscillators. Edge-replicated padding
    # gives Neumann boundaries -> the frame edges reflect.

    def _step_field(self, dt):
        c_dx = WAVE_SPEED_PX_S * dt / WAVE_GRID_PX
        s2 = c_dx * c_dx
        delta = min(1.0, 2.0 * dt / WAVE_DECAY_TAU_S)
        u, up = self._u, self._u_prev
        pad = np.pad(u, 1, mode="edge")
        # 9-point isotropic Laplacian — the plain 5-point stencil propagates
        # measurably faster along the axes than the diagonals, which turns
        # circular ripples visibly square after a few wavelengths.
        lap = (4.0 * (pad[:-2, 1:-1] + pad[2:, 1:-1]
                      + pad[1:-1, :-2] + pad[1:-1, 2:])
               + (pad[:-2, :-2] + pad[:-2, 2:] + pad[2:, :-2] + pad[2:, 2:])
               - 20.0 * u) / 6.0
        u_next = (2.0 - delta) * u - (1.0 - delta) * up + s2 * lap

        gh, gw = u.shape
        for s in self.sources:
            age = self._field_t - s.born
            if age < 0.0:
                continue
            ramp = min(1.0, age / WAVE_RAMP_S)
            target = WAVE_AMP * ramp * math.sin(2.0 * math.pi * s.freq * age)
            gx = min(gw - 1, max(0, int(s.x / WAVE_GRID_PX)))
            gy = min(gh - 1, max(0, int(s.y / WAVE_GRID_PX)))
            x0, x1 = max(0, gx - 2), min(gw, gx + 3)
            y0, y1 = max(0, gy - 2), min(gh, gy + 3)
            yy, xx = np.mgrid[y0:y1, x0:x1]
            w = np.exp(-((xx - gx) ** 2 + (yy - gy) ** 2) / 2.0).astype(np.float32)
            u_next[y0:y1, x0:x1] = (u_next[y0:y1, x0:x1] * (1.0 - w)
                                    + target * w)

        self._u_prev = u
        self._u = u_next

    def _advance_field(self):
        if self._u is None:
            gw = max(2, self.w // WAVE_GRID_PX)
            gh = max(2, self.h // WAVE_GRID_PX)
            self._u = np.zeros((gh, gw), np.float32)
            self._u_prev = np.zeros((gh, gw), np.float32)
            self._field_t = self._clock
        # CFL-stable sub-steps up to the clock; after a stall (draw not
        # called for a while) integrate at most a quarter second of it.
        dt_max = 0.6 * WAVE_GRID_PX / WAVE_SPEED_PX_S
        if self._clock - self._field_t > 0.25:
            self._field_t = self._clock - 0.25
        while self._field_t < self._clock - 1e-9:
            dt = min(dt_max, self._clock - self._field_t)
            self._field_t += dt
            self._step_field(dt)

    # Crests tint toward icy white, troughs toward deep blue (BGR).
    _CREST_BGR = np.array([255, 238, 190], np.uint8)
    _TROUGH_BGR = np.array([150, 70, 20], np.uint8)

    def draw(self, frame):
        self._advance_field()
        u = self._u
        # Overlay colour + per-pixel blend weight are built at GRID
        # resolution and upscaled, so the only full-resolution pass is one
        # SIMD cv2.blendLinear — the float-numpy version of this composite
        # cost ~75 ms/frame at 720p, this is a few ms.
        color = np.where((u > 0.0)[..., None], self._CREST_BGR,
                         self._TROUGH_BGR)
        w = np.clip(np.abs(u) * 0.45, 0.0, 0.7).astype(np.float32)
        color = cv2.resize(color, (self.w, self.h),
                           interpolation=cv2.INTER_LINEAR)
        w = cv2.resize(w, (self.w, self.h), interpolation=cv2.INTER_LINEAR)
        frame[:] = cv2.blendLinear(frame, color, 1.0 - w, w)

        # Source markers: a dot + a ring, highlighted while grabbed.
        for s in self.sources:
            cx, cy = int(s.x), int(s.y)
            hot = s is self.grab_src
            col = (255, 255, 255) if hot else (230, 214, 170)
            cv2.circle(frame, (cx, cy), 5, col, -1, cv2.LINE_AA)
            cv2.circle(frame, (cx, cy), 12, col, 2 if hot else 1, cv2.LINE_AA)
            cv2.putText(frame, f"{s.freq:g} Hz", (cx + 16, cy - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 1, cv2.LINE_AA)


# --- Vtuber / Puppet interactable ---------------------------------------


class Puppet:
    """A cosmic-mascot avatar puppeteered by the live landmarks.

    Pure rendering happens in the browser (and a cv2 fallback); this class
    only carries a tiny per-frame snapshot (a spawn clock for the idle bob,
    the pinch strength for the mouth). The renderer reads the hands (always
    tracked) — and the body pose when ``HALL_POSE=1`` — straight from the
    published state, so no landmark data is duplicated here. When the puppet
    is active the frontend hides the raw skeleton and dims the camera so the
    character stands alone.
    """

    def __init__(self, frame_width, frame_height):
        self.w = frame_width
        self.h = frame_height
        self._spawn_time = time.monotonic()
        # Latest max pinch progress across hands — drives the mouth. Held
        # here (not just in the browser) so the cv2 fallback can react too.
        self._mouth = 0.0
        self._hand_result = None
        self._pose = None

    @property
    def grabbed(self):
        # Not a grab-target, but reporting True while a hand is pinching
        # retires the onboarding hint once the user drives the mouth.
        return self._mouth > 0.5

    def update(self, hand_result, pose_landmarks):
        self._hand_result = hand_result
        self._pose = pose_landmarks
        mouth = 0.0
        if hand_result is not None:
            for i in range(len(hand_result.hand_landmarks)):
                info = pinch_info(hand_id(hand_result, i))
                if info is not None:
                    mouth = max(mouth, info.progress)
        self._mouth = mouth

    def to_state(self):
        return {
            "type": "vtuber",
            "t": round((time.monotonic() - self._spawn_time) % 1000.0, 3),
            "mouth": round(self._mouth, 3),
        }

    def draw(self, frame):
        # cv2 fallback: dim the scene, then a minimal face + paws so the
        # window/stream path still shows *something* coherent. The web path
        # renders the rich avatar.
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (self.w, self.h), (12, 8, 18), -1)
        cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

        hands = []
        if self._hand_result is not None:
            for lms in self._hand_result.hand_landmarks:
                wrist = lms[0]
                hands.append((int(wrist.x * self.w), int(wrist.y * self.h)))

        if hands:
            hx = sum(p[0] for p in hands) // len(hands)
            hy = sum(p[1] for p in hands) // len(hands)
        else:
            hx, hy = self.w // 2, self.h // 2
        bob = int(10 * math.sin((time.monotonic() - self._spawn_time)
                                * 2 * math.pi / PUPPET_IDLE_BOB_S))
        head_y = max(120, hy - 200) + bob
        head = (hx, head_y)
        rr = 90
        cv2.circle(frame, head, rr + 6, (90, 60, 130), -1, cv2.LINE_AA)
        cv2.circle(frame, head, rr, (245, 220, 170), -1, cv2.LINE_AA)
        # Eyes.
        for ex in (-32, 32):
            cv2.circle(frame, (head[0] + ex, head_y - 14), 12,
                       (40, 30, 30), -1, cv2.LINE_AA)
        # Mouth: opens with the pinch.
        mh = int(6 + 26 * self._mouth)
        cv2.ellipse(frame, (head[0], head_y + 34), (30, mh), 0, 0, 360,
                    (40, 30, 30), -1, cv2.LINE_AA)
        # Paws at each hand + noodle arms to the head.
        for hp in hands:
            cv2.line(frame, head, hp, (245, 220, 170), 10, cv2.LINE_AA)
            cv2.circle(frame, hp, 26, (245, 220, 170), -1, cv2.LINE_AA)
            cv2.circle(frame, hp, 26, (90, 60, 130), 3, cv2.LINE_AA)
