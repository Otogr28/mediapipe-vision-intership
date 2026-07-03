from rendering.gl_lensing import LensingRenderer
from ui.button import Button
from ui.hints import IntroOverlay, PinchHint
from ui.interactables import BlackHole, BouncingSphere, SixSevenCounter, Slingshot

MENU_BTN_W, MENU_BTN_H = 260, 70
RESET_W, RESET_H = 130, 50


class UIManager:
    """Manages all UI state, buttons, and interactable objects."""

    def __init__(self, frame_w, frame_h):
        self.frame_w = frame_w
        self.frame_h = frame_h
        self.state = "menu"
        self.spheres = []
        # The single experiment currently running in the "experiments" state
        # (a BlackHole, Slingshot, …), or None while its picker is shown. Only
        # one experiment is active at a time.
        self._active_experiment = None
        self._sixseven = None
        # Lazy-initialised the first time the user spawns the black hole —
        # postpones GL context creation until something actually needs it, and
        # keeps startup cost out of the camera-only path.
        self._lensing_renderer = None

        # Onboarding overlays. The intro splash plays once at startup; the
        # bottom-right pinch hint shows until the user first interacts.
        self._intro = IntroOverlay(frame_w, frame_h)
        self._pinch_hint = PinchHint(frame_w, frame_h)
        self._has_interacted = False

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

        # Experiment picker: one spawn button per experiment, laid out in a
        # row. Whichever is pressed becomes the single active experiment.
        self._black_hole_btn = Button(
            x=20, y=20, width=150, height=50,
            label="Black Hole",
            on_click=self._spawn_black_hole,
        )
        self._slingshot_btn = Button(
            x=20 + 150 + 10, y=20, width=150, height=50,
            label="Slingshot",
            on_click=self._spawn_slingshot,
        )
        self._experiment_btns = [self._black_hole_btn, self._slingshot_btn]

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
        self._active_experiment = BlackHole(self.frame_w, self.frame_h, self._lensing_renderer)

    def _spawn_slingshot(self):
        self._active_experiment = Slingshot(self.frame_w, self.frame_h)

    def _spawn_sixseven(self):
        # Re-pressing the button while a counter is active resets the
        # tally — gives users a way to zero the count without leaving the
        # mode (the global Reset button drops the counter entirely).
        self._sixseven = SixSevenCounter(self.frame_w, self.frame_h)

    def _reset(self):
        self.spheres.clear()
        self._active_experiment = None
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
            if self._active_experiment is None:
                for btn in self._experiment_btns:
                    btn.update(hand_result, pose_landmarks, self.frame_w, self.frame_h)
            else:
                self._active_experiment.update(hand_result, pose_landmarks)
            self._reset_btn.update(hand_result, pose_landmarks, self.frame_w, self.frame_h)

        if self._detect_interaction():
            self._has_interacted = True
        self._pinch_hint.update(pose_landmarks is not None, self._has_interacted)

    def _detect_interaction(self):
        """True on a frame where the user pressed a button or grabbed an
        object — used to retire the onboarding pinch hint."""
        if self.state == "menu":
            return self._menu_interactables_btn.pressed or self._menu_experiments_btn.pressed
        if self.state == "interactables":
            return (self._sphere_btn.pressed or self._sixseven_btn.pressed
                    or self._reset_btn.pressed
                    or any(s.grabbed for s in self.spheres))
        if self.state == "experiments":
            if self._active_experiment is None:
                return self._reset_btn.pressed or any(b.pressed for b in self._experiment_btns)
            return self._reset_btn.pressed or self._active_experiment.grabbed
        return False

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
            # The active experiment draws first (e.g. the BH's full-frame
            # distortion) so the picker/reset buttons stay readable on top.
            if self._active_experiment is not None:
                self._active_experiment.draw(frame)
            else:
                for btn in self._experiment_btns:
                    btn.draw(frame)
            self._reset_btn.draw(frame)

        # Onboarding overlays sit on top of the scene. The bottom-right hint
        # yields to the intro splash so they never stack.
        if self._intro.active:
            self._intro.draw(frame)
        else:
            self._pinch_hint.draw(frame)
