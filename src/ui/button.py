import cv2

from config import PINCH_RATIO
from detection.gestures import pinch_state, hand_id

COOLDOWN_FRAMES = 25   # frames before the button can fire again


class Button:
    def __init__(self, x, y, width, height, label, on_click, font_scale=0.7):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.label = label
        self.on_click = on_click
        self.font_scale = font_scale
        self._cooldown = 0
        self.hovered = False
        self.pressed = False

    def update(self, hand_result, pose_landmarks, frame_w, frame_h):
        self.hovered = False
        self.pressed = False

        if self._cooldown > 0:
            self._cooldown -= 1

        if hand_result is None:
            return

        for i, hand_landmarks in enumerate(hand_result.hand_landmarks):
            hid = hand_id(hand_result, i)
            pinching, _held, (cx, cy) = pinch_state(
                hand_landmarks, pose_landmarks, frame_w, frame_h, PINCH_RATIO,
                hand_id=hid,
            )

            inside = (self.x <= cx <= self.x + self.width and
                      self.y <= cy <= self.y + self.height)

            if inside:
                self.hovered = True
                if pinching and self._cooldown == 0:
                    self.pressed = True
                    self._cooldown = COOLDOWN_FRAMES
                    self.on_click()
                break  # one hand is enough

    def draw(self, frame):
        if self.pressed:
            bg_color = (0, 200, 100)
        elif self.hovered:
            bg_color = (50, 130, 220)
        else:
            bg_color = (30, 30, 30)

        cv2.rectangle(frame,
                      (self.x, self.y),
                      (self.x + self.width, self.y + self.height),
                      bg_color, -1)
        cv2.rectangle(frame,
                      (self.x, self.y),
                      (self.x + self.width, self.y + self.height),
                      (120, 120, 120), 2)

        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = self.font_scale
        thick = 2
        (tw, th), _ = cv2.getTextSize(self.label, font, scale, thick)
        lx = self.x + (self.width - tw) // 2
        ly = self.y + (self.height + th) // 2
        cv2.putText(frame, self.label, (lx, ly), font, scale,
                    (255, 255, 255), thick, cv2.LINE_AA)
