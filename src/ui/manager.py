from rendering.gl_lensing import LensingRenderer
from ui.button import Button
from ui.interactables import BlackHole, BouncingSphere, SixSevenCounter

MENU_BTN_W, MENU_BTN_H = 260, 70
RESET_W, RESET_H = 130, 50


class UIManager:
    """Manages all UI state, buttons, and interactable objects."""

    def __init__(self, frame_w, frame_h):
        self.frame_w = frame_w
        self.frame_h = frame_h
        self.state = "menu"
        self.spheres = []
        self._black_hole = None
        self._sixseven = None
        # Lazy-initialised the first time the user enters the "experiments"
        # state — postpones GL context creation until something actually
        # needs it, and keeps startup cost out of the camera-only path.
        self._lensing_renderer = None

        self._build_buttons()

    def _build_buttons(self):
        fw, fh = self.frame_w, self.frame_h

        num_btns = 2
        gap = 16
        total_w = num_btns * MENU_BTN_W + (num_btns - 1) * gap
        start_x = (fw - total_w) // 2
        top_y = 12

        self._menu_interactables_btn = Button(
            x=start_x, y=top_y,
            width=MENU_BTN_W, height=MENU_BTN_H,
            label="Interactable Figures",
            on_click=lambda: self._set_state("interactables"),
            font_scale=0.55,
        )
        self._menu_experiments_btn = Button(
            x=start_x + MENU_BTN_W + gap, y=top_y,
            width=MENU_BTN_W, height=MENU_BTN_H,
            label="Experiments",
            on_click=lambda: self._set_state("experiments"),
        )

        self._sphere_btn = Button(
            x=20, y=20, width=120, height=50,
            label="Sphere",
            on_click=self._add_sphere,
        )

        self._sixseven_btn = Button(
            x=20 + 120 + 10, y=20, width=170, height=50,
            label="6 7 Counter",
            on_click=self._spawn_sixseven,
            font_scale=0.6,
        )

        self._black_hole_btn = Button(
            x=20, y=20, width=150, height=50,
            label="Black Hole",
            on_click=self._spawn_black_hole,
        )

        self._reset_btn = Button(
            x=fw - RESET_W - 20, y=fh - RESET_H - 20,
            width=RESET_W, height=RESET_H,
            label="Reset",
            on_click=self._reset,
        )

    def _set_state(self, new_state):
        self.state = new_state

    def _add_sphere(self):
        self.spheres.append(BouncingSphere(self.frame_w, self.frame_h))

    def _spawn_black_hole(self):
        if self._lensing_renderer is None:
            self._lensing_renderer = LensingRenderer(self.frame_w, self.frame_h)
        self._black_hole = BlackHole(self.frame_w, self.frame_h, self._lensing_renderer)

    def _spawn_sixseven(self):
        # Re-pressing the button while a counter is active resets the
        # tally — gives users a way to zero the count without leaving the
        # mode (the global Reset button drops the counter entirely).
        self._sixseven = SixSevenCounter(self.frame_w, self.frame_h)

    def _reset(self):
        self.spheres.clear()
        self._black_hole = None
        self._sixseven = None
        self.state = "menu"

    def update(self, hand_result, pose_landmarks):
        if self.state == "menu":
            self._menu_interactables_btn.update(hand_result, pose_landmarks, self.frame_w, self.frame_h)
            self._menu_experiments_btn.update(hand_result, pose_landmarks, self.frame_w, self.frame_h)

        elif self.state == "interactables":
            self._sphere_btn.update(hand_result, pose_landmarks, self.frame_w, self.frame_h)
            self._sixseven_btn.update(hand_result, pose_landmarks, self.frame_w, self.frame_h)
            for s in self.spheres:
                s.update(hand_result, pose_landmarks)
            if self._sixseven is not None:
                self._sixseven.update(hand_result, pose_landmarks)
            self._reset_btn.update(hand_result, pose_landmarks, self.frame_w, self.frame_h)

        elif self.state == "experiments":
            if self._black_hole is None:
                self._black_hole_btn.update(hand_result, pose_landmarks, self.frame_w, self.frame_h)
            else:
                self._black_hole.update(hand_result, pose_landmarks)
            self._reset_btn.update(hand_result, pose_landmarks, self.frame_w, self.frame_h)

    def draw(self, frame):
        if self.state == "menu":
            self._menu_interactables_btn.draw(frame)
            self._menu_experiments_btn.draw(frame)

        elif self.state == "interactables":
            self._sphere_btn.draw(frame)
            self._sixseven_btn.draw(frame)
            for s in self.spheres:
                s.draw(frame)
            if self._sixseven is not None:
                self._sixseven.draw(frame)
            self._reset_btn.draw(frame)

        elif self.state == "experiments":
            # BH distortion runs first so the spawn/reset buttons stay
            # readable on top of the lensed background.
            if self._black_hole is not None:
                self._black_hole.draw(frame)
            else:
                self._black_hole_btn.draw(frame)
            self._reset_btn.draw(frame)
