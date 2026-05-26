import random
import time

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
)
from detection.gestures import hand_id, pinch_state


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
