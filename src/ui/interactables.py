import math
import random
import time
from collections import deque

import cv2
import numpy as np

from config import (
    BH_DEFAULT_POS_FACTOR,
    BH_DISK_BRIGHTNESS,
    BH_DISK_INNER_FACTOR,
    BH_DISK_OUTER_FACTOR,
    BH_DISK_ROTATION_SPEED,
    BH_DISK_TILT_RAD,
    BH_EINSTEIN_RADIUS_PX,
    BH_GRAB_RADIUS,
    PINCH_HOLD_RATIO,
    PINCH_RATIO,
    SIXSEVEN_FLASH_FRAMES,
    SIXSEVEN_HYSTERESIS,
    SIXSEVEN_MIN_VISIBILITY,
)
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
        self.grab_offset_x = 0.0
        self.grab_offset_y = 0.0

    def update(self, hand_result, pose_landmarks):
        if hand_result is not None:
            grabbed_this_frame = False

            for i, hand_landmarks in enumerate(hand_result.hand_landmarks):
                hid = hand_id(hand_result, i)
                pinching, held, (mx, my) = pinch_state(
                    hand_landmarks, pose_landmarks, self.w, self.h, PINCH_RATIO,
                    hold_ratio=PINCH_HOLD_RATIO, hand_id=hid,
                )

                # Maintain an existing grab while the hand stays closed;
                # only the rapid-close event (`pinching`) can initiate a
                # new grab, so an already-closed hand sliding over the
                # sphere will not pick it up.
                sphere_dist = ((self.x - mx) ** 2 + (self.y - my) ** 2) ** 0.5
                can_grab = (self.grabbed and held) or (
                    pinching and sphere_dist < GRAB_RADIUS
                )

                if can_grab:
                    if not self.grabbed:
                        self.grab_offset_x = self.x - mx
                        self.grab_offset_y = self.y - my

                    new_x = mx + self.grab_offset_x
                    new_y = my + self.grab_offset_y
                    self.vx = new_x - self.x
                    self.vy = new_y - self.y
                    self.x = new_x
                    self.y = new_y
                    self.grabbed = True
                    grabbed_this_frame = True
                    break

            if not grabbed_this_frame:
                self.grabbed = False
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
        else:
            self.grabbed = False

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
        self.grab_offset_x = 0.0
        self.grab_offset_y = 0.0
        self._renderer = renderer
        # Anchor for the rotation clock so successive spawns start from
        # phase zero instead of inheriting elapsed time from the process.
        self._spawn_time = time.monotonic()

    def update(self, hand_result, pose_landmarks):
        if hand_result is None:
            self.grabbed = False
            return

        grabbed_this_frame = False
        for i, hand_landmarks in enumerate(hand_result.hand_landmarks):
            hid = hand_id(hand_result, i)
            pinching, held, (mx, my) = pinch_state(
                hand_landmarks, pose_landmarks, self.w, self.h, PINCH_RATIO,
                hold_ratio=PINCH_HOLD_RATIO, hand_id=hid,
            )

            dist = ((self.x - mx) ** 2 + (self.y - my) ** 2) ** 0.5
            can_grab = (self.grabbed and held) or (
                pinching and dist < BH_GRAB_RADIUS
            )

            if can_grab:
                if not self.grabbed:
                    self.grab_offset_x = self.x - mx
                    self.grab_offset_y = self.y - my
                self.x = mx + self.grab_offset_x
                self.y = my + self.grab_offset_y
                self.grabbed = True
                grabbed_this_frame = True
                break

        if not grabbed_this_frame:
            self.grabbed = False

    def draw(self, frame):
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
SLING_DT = 1.0 / 30.0        # fixed physics timestep (s) — one video frame

SLING_G = 9.81               # gravitational acceleration (m/s^2), Earth
SLING_BALL_MASS = 1.0        # mass of every ball (kg); equal mass keeps the
                             # ball-vs-ball collision a clean velocity exchange
SLING_DRAG_COEF = 0.15       # linear air-drag coefficient b in F = -b*v (N.s/m)

SLING_LAUNCH_GAIN = 5.4      # launch speed per metre of pull (1/s);
                             # a full 2.6 m pull -> ~14 m/s
SLING_MAX_PULL_PX = 260      # cap on pull-back distance (screen px)
SLING_GRAB_RADIUS_PX = 90    # max screen distance from the anchor to start aiming

SLING_WALL_RESTITUTION = 0.7
SLING_GROUND_RESTITUTION = 0.55
SLING_GROUND_FRICTION = 0.8  # fraction of tangential speed kept per floor bounce
SLING_COLLISION_RESTITUTION = 0.85  # bounciness of ball-vs-ball impacts
SLING_REST_SPEED = 0.3       # m/s; below this on the floor a ball is "at rest"

SLING_RADIUS_PX = 22         # ball radius on screen (px) -> 0.22 m
SLING_TRAIL_LEN = 40
SLING_MAX_PROJECTILES = 8
SLING_PREDICT_STEPS = 45     # look-ahead frames for the aim trajectory
SLING_CONTACT_DECAY = 0.6    # per-frame fade of the transient contact-force arrow

# Force-vector overlay.
SLING_FORCE_PX_PER_N = 6.0     # arrow length drawn per newton
SLING_MIN_FORCE_DRAW_N = 0.05  # skip arrows for negligible forces
SLING_COL_WEIGHT = (0, 180, 255)   # BGR amber — weight  m*g
SLING_COL_DRAG = (255, 200, 0)     # BGR cyan  — air drag -b*v
SLING_COL_NORMAL = (0, 235, 0)     # BGR green — contact / normal reaction
SLING_COL_NET = (240, 240, 240)    # BGR white — net force


class _Projectile:
    __slots__ = ("x", "y", "vx", "vy", "trail", "resting", "cfx", "cfy")

    def __init__(self, x, y, vx, vy):
        self.x = x     # position, metres (screen frame; +y points down)
        self.y = y
        self.vx = vx   # velocity, m/s
        self.vy = vy
        self.trail = deque(maxlen=SLING_TRAIL_LEN)
        self.resting = False
        # Net contact force this frame (N) — floor/wall/ball reactions — kept
        # only for the force overlay. Weight and drag are recomputed from state.
        self.cfx = 0.0
        self.cfy = 0.0


class Slingshot:
    """Projectile-motion experiment in SI units: pull back and release to launch.

    Physics runs in metres / seconds / kilograms / newtons; ``SLING_PX_PER_M``
    and ``SLING_DT`` map that world onto the video's pixels and frames. A ball
    rests on a fixed anchor; a pinch near it grabs the ball, the hand pulls it
    back (rubber-band aim, capped) and a dotted arc previews the shot while a
    HUD reads out launch angle, speed (m/s) and kinetic energy (J). Releasing
    launches it under real gravity (9.81 m/s^2) with linear air drag; balls
    bounce off the walls and floor with restitution and collide elastically
    with each other, and every ball draws the force vectors acting on it
    (weight, drag, contact, net). Up to ``SLING_MAX_PROJECTILES`` shots coexist
    (oldest dropped past the cap). Like the black hole it reuses the
    pose-scaled pinch, so the shoulders must be visible to aim.
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
        self.pull_x = self.anchor_x
        self.pull_y = self.anchor_y

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
        # Fires opposite to the pull: pull down-left -> launches up-right.
        # (anchor - pull) is in metres; * gain (1/s) gives m/s.
        return (
            (self.anchor_x - self.pull_x) * SLING_LAUNCH_GAIN,
            (self.anchor_y - self.pull_y) * SLING_LAUNCH_GAIN,
        )

    def _fire(self):
        # Capture the launch point/velocity from the current pull BEFORE
        # resetting the aim back to the anchor.
        launch_x, launch_y = self.pull_x, self.pull_y
        vx, vy = self._launch_velocity()
        self.aiming = False
        self.pull_x, self.pull_y = self.anchor_x, self.anchor_y
        # Ignore a dead-fire (pull too small to matter, < SLING_REST_SPEED m/s).
        if math.hypot(vx, vy) < SLING_REST_SPEED:
            return
        self.projectiles.append(_Projectile(launch_x, launch_y, vx, vy))
        if len(self.projectiles) > SLING_MAX_PROJECTILES:
            self.projectiles.pop(0)

    def update(self, hand_result, pose_landmarks):
        if hand_result is not None:
            aiming_this_frame = False
            anchor_x_px = self.anchor_x * SLING_PX_PER_M
            anchor_y_px = self.anchor_y * SLING_PX_PER_M
            for i, hand_landmarks in enumerate(hand_result.hand_landmarks):
                hid = hand_id(hand_result, i)
                # The pinch cursor (mx, my) comes back in pixels.
                pinching, held, (mx, my) = pinch_state(
                    hand_landmarks, pose_landmarks, self.w_px, self.h_px, PINCH_RATIO,
                    hold_ratio=PINCH_HOLD_RATIO, hand_id=hid,
                )
                anchor_dist = math.hypot(anchor_x_px - mx, anchor_y_px - my)
                # Only a rapid close near the anchor starts an aim; once
                # aiming, `held` keeps it while the fingers stay roughly shut.
                can_aim = (self.aiming and held) or (
                    pinching and anchor_dist < SLING_GRAB_RADIUS_PX
                )
                if can_aim:
                    # Convert the cursor to metres for the physics world.
                    self.pull_x, self.pull_y = self._clamp_pull(
                        mx / SLING_PX_PER_M, my / SLING_PX_PER_M)
                    self.aiming = True
                    aiming_this_frame = True
                    break

            # Fingers opened this frame -> release the shot.
            if self.aiming and not aiming_this_frame:
                self._fire()
        elif self.aiming:
            # Hand lost mid-pull: fire with the pull we had (better than
            # silently swallowing the shot).
            self._fire()

        # Fade last frame's transient contact-force arrows (bounces / impacts).
        for p in self.projectiles:
            p.cfx *= SLING_CONTACT_DECAY
            p.cfy *= SLING_CONTACT_DECAY
        # Free-flight motion + walls first, then ball-vs-ball collisions so
        # every spawned ball obeys the same physics against the others; trails
        # are recorded last, after positions have settled for the frame.
        for p in self.projectiles:
            self._step(p)
        self._resolve_collisions()
        for p in self.projectiles:
            if p.resting:
                # A ball parked on the floor: the steady normal reaction
                # exactly balances its weight (so the net force reads zero).
                p.cfx, p.cfy = 0.0, -SLING_BALL_MASS * SLING_G
            p.trail.append((self._px(p.x), self._px(p.y)))

    def _step(self, p):
        if p.resting:
            return
        m = SLING_BALL_MASS
        # Forces (N): weight down (+y) plus linear air drag opposing velocity.
        # a = F / m, integrated with semi-implicit Euler over SLING_DT seconds.
        fx = -SLING_DRAG_COEF * p.vx
        fy = m * SLING_G - SLING_DRAG_COEF * p.vy
        p.vx += (fx / m) * SLING_DT
        p.vy += (fy / m) * SLING_DT
        p.x += p.vx * SLING_DT
        p.y += p.vy * SLING_DT
        r = self.r

        # Wall / floor bounces. Each records the reaction as a contact force
        # (impulse / dt, in newtons) for the force overlay.
        if p.x - r <= 0:
            p.x = r
            before = p.vx
            p.vx = abs(p.vx) * SLING_WALL_RESTITUTION
            p.cfx += m * (p.vx - before) / SLING_DT
        elif p.x + r >= self.w:
            p.x = self.w - r
            before = p.vx
            p.vx = -abs(p.vx) * SLING_WALL_RESTITUTION
            p.cfx += m * (p.vx - before) / SLING_DT

        if p.y - r <= 0:
            p.y = r
            before = p.vy
            p.vy = abs(p.vy) * SLING_WALL_RESTITUTION
            p.cfy += m * (p.vy - before) / SLING_DT
        elif p.y + r >= self.h:
            p.y = self.h - r
            before = p.vy
            p.vy = -abs(p.vy) * SLING_GROUND_RESTITUTION
            p.cfy += m * (p.vy - before) / SLING_DT
            p.vx *= SLING_GROUND_FRICTION
            # Settle to rest once the bounce energy is spent. A resting ball
            # skips integration until a collision wakes it (see
            # `_resolve_collisions`), so a pile can still be knocked apart.
            if abs(p.vy) < SLING_REST_SPEED and abs(p.vx) < SLING_REST_SPEED:
                p.vx = p.vy = 0.0
                p.resting = True

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
                    # Impulse (m*j) as an average force over the timestep.
                    f = m * j / SLING_DT
                    pa.cfx -= f * nx
                    pa.cfy -= f * ny
                    pb.cfx += f * nx
                    pb.cfy += f * ny
                    pa.resting = pb.resting = False

        # Positional correction can shove a ball past an edge — clamp back in.
        for p in self.projectiles:
            p.x = min(max(p.x, r), self.w - r)
            p.y = min(max(p.y, r), self.h - r)

    def _predicted_arc(self):
        """Forward-simulate the pending shot for a short dotted preview."""
        vx, vy = self._launch_velocity()
        x, y = self.pull_x, self.pull_y
        r = self.r
        m = SLING_BALL_MASS
        pts = []
        for _ in range(SLING_PREDICT_STEPS):
            vx += (-SLING_DRAG_COEF * vx / m) * SLING_DT
            vy += (SLING_G - SLING_DRAG_COEF * vy / m) * SLING_DT
            x += vx * SLING_DT
            y += vy * SLING_DT
            pts.append((self._px(x), self._px(y)))
            if x - r <= 0 or x + r >= self.w or y + r >= self.h:
                break
        return pts

    def _aim_readout(self):
        """(angle_deg, speed_mps, ke_joules) for the pending shot. Angle is
        measured from the horizontal (0 = right, +90 = straight up, negatives =
        downward); speed is the launch speed in m/s and ke its kinetic energy."""
        vx, vy = self._launch_velocity()
        speed = math.hypot(vx, vy)                   # m/s
        ke = 0.5 * SLING_BALL_MASS * speed * speed    # joules
        # Screen y grows downward, so negate vy to make "up" a positive angle.
        angle = math.degrees(math.atan2(-vy, vx))
        return angle, speed, ke

    def _draw_readout(self, frame, angle, speed, ke):
        """Translucent SI readout (angle / launch speed / KE) above the anchor."""
        label = f"ANGLE {angle:+.0f} deg   v0 {speed:.1f} m/s   KE {ke:.0f} J"
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale, thick, pad = 0.6, 2, 8
        (tw, th), base = cv2.getTextSize(label, font, scale, thick)
        box_w = tw + pad * 2
        box_h = th + base + pad * 2
        box_x = int(self.anchor_x * SLING_PX_PER_M - box_w / 2)
        box_y = int(self.anchor_y * SLING_PX_PER_M - SLING_RADIUS_PX - 24 - box_h)

        overlay = frame.copy()
        cv2.rectangle(overlay, (box_x, box_y), (box_x + box_w, box_y + box_h),
                      (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)
        cv2.putText(frame, label, (box_x + pad, box_y + pad + th), font, scale,
                    (0, 255, 255), thick, cv2.LINE_AA)

    @staticmethod
    def _draw_force_arrow(frame, cx, cy, fx, fy, color):
        """Draw one force vector (newtons) from a ball centre, scaled to px."""
        if math.hypot(fx, fy) < SLING_MIN_FORCE_DRAW_N:
            return
        ex = int(cx + fx * SLING_FORCE_PX_PER_N)
        ey = int(cy + fy * SLING_FORCE_PX_PER_N)
        cv2.arrowedLine(frame, (cx, cy), (ex, ey), color, 2, cv2.LINE_AA,
                        tipLength=0.25)

    def _draw_legend(self, frame):
        """Colour key for the force overlay + the SI constants in play."""
        font = cv2.FONT_HERSHEY_SIMPLEX
        rows = [
            (SLING_COL_WEIGHT, "weight  m*g"),
            (SLING_COL_DRAG, "drag  -b*v"),
            (SLING_COL_NORMAL, "contact / normal"),
            (SLING_COL_NET, "net force"),
        ]
        x, y, line_h = 20, 84, 22
        box_w = 232
        box_h = line_h * (len(rows) + 1) + 14
        overlay = frame.copy()
        cv2.rectangle(overlay, (x, y), (x + box_w, y + box_h), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)
        cy = y + 8
        for color, text in rows:
            cy += line_h
            cv2.line(frame, (x + 10, cy - 5), (x + 34, cy - 5), color, 3, cv2.LINE_AA)
            cv2.putText(frame, text, (x + 42, cy), font, 0.45, (230, 230, 230), 1,
                        cv2.LINE_AA)
        cy += line_h
        cv2.putText(frame,
                    f"g={SLING_G} m/s2  m={SLING_BALL_MASS:.1f} kg  b={SLING_DRAG_COEF} Ns/m",
                    (x + 10, cy), font, 0.38, (180, 180, 180), 1, cv2.LINE_AA)

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
            for i, (tx, ty) in enumerate(self._predicted_arc()):
                if i % 2 == 0:
                    cv2.circle(frame, (tx, ty), 3, (0, 255, 255), -1)
            cv2.circle(frame, (px, py), SLING_RADIUS_PX, (0, 140, 255), -1)
            cv2.circle(frame, (px, py), SLING_RADIUS_PX, (255, 255, 255), 2, cv2.LINE_AA)
            angle, speed, ke = self._aim_readout()
            self._draw_readout(frame, angle, speed, ke)
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
            # linear drag, the contact reaction, and their vector sum (net).
            weight = (0.0, m * SLING_G)
            drag = (-SLING_DRAG_COEF * p.vx, -SLING_DRAG_COEF * p.vy)
            contact = (p.cfx, p.cfy)
            self._draw_force_arrow(frame, cx, cy, *weight, SLING_COL_WEIGHT)
            self._draw_force_arrow(frame, cx, cy, *drag, SLING_COL_DRAG)
            self._draw_force_arrow(frame, cx, cy, *contact, SLING_COL_NORMAL)
            net = (weight[0] + drag[0] + contact[0],
                   weight[1] + drag[1] + contact[1])
            self._draw_force_arrow(frame, cx, cy, *net, SLING_COL_NET)
