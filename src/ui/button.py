import cv2

from config import BUTTON_COOLDOWN_FRAMES, BUTTON_STICKY_PAD_FRAC
from detection.gestures import hand_id, pinch_info


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
        # Sticky "this option is chosen" flag for radio-style palettes (e.g.
        # the Orbitals body-type picker). Purely cosmetic — set by the owner,
        # read by the renderer; the click logic never looks at it.
        self.selected = False

    def _inside(self, x, y, pad=0):
        return (self.x - pad <= x <= self.x + self.width + pad and
                self.y - pad <= y <= self.y + self.height + pad)

    def update(self, hand_result, pose_landmarks, frame_w, frame_h):
        # pose_landmarks / frame dims are unused since the pinch pipeline
        # became a per-frame snapshot (see detection/gestures.py); the
        # signature is kept uniform with the other per-frame updates.
        was_hovered = self.hovered
        self.hovered = False
        self.pressed = False

        if self._cooldown > 0:
            self._cooldown -= 1

        if hand_result is None:
            return

        # Sticky target: once hovered, the hit rect inflates a little so
        # cursor jitter at the border cannot flicker the hover or drop a
        # click. Entering still requires the base rect (hysteresis); the
        # pad comes from the HEIGHT so it stays under every button gap.
        pad = (int(BUTTON_STICKY_PAD_FRAC * self.height)
               if was_hovered else 0)

        for i in range(len(hand_result.hand_landmarks)):
            info = pinch_info(hand_id(hand_result, i))
            if info is None:
                continue
            if self._inside(*info.cursor, pad):
                self.hovered = True
            # Hover-latch: the click is hit-tested where the close gesture
            # STARTED (press_cursor), so the hand drifting during the close
            # cannot slide the click off its target — nor fake one onto it
            # (a close begun outside doesn't count even if it ends inside).
            if (info.pinching and self._cooldown == 0
                    and self._inside(*info.press_cursor, pad)):
                self.pressed = True
                self._cooldown = BUTTON_COOLDOWN_FRAMES
                self.on_click()
                break

    def to_state(self, btn_id):
        """Serializable snapshot for the web frontend (pure display: the
        browser renders this rect/flags verbatim, hit-testing stays here)."""
        return {
            "id": btn_id,
            "label": self.label,
            "rect": [self.x, self.y, self.width, self.height],
            "hovered": self.hovered,
            "pressed": self.pressed,
            "selected": self.selected,
        }

    def draw(self, frame):
        if self.pressed:
            bg_color = (0, 200, 100)
        elif self.hovered:
            bg_color = (50, 130, 220)
        elif self.selected:
            bg_color = (70, 60, 20)
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
