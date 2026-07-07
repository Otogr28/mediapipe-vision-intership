import cv2

from config import DEBUG_HUD
from detection.gestures import update_pinches
from rendering.gl_lensing import LensingRenderer
from ui.button import Button
from ui.cursor import PinchCursor
from ui.debug_hud import DebugHUD
from ui.hints import IntroOverlay, PinchHint
from ui.interactables import (BlackHole, BouncingSphere, SixSevenCounter,
                              Slingshot)

MENU_BTN_W, MENU_BTN_H = 260, 70
RESET_W, RESET_H = 130, 50
SPEED_BTN = 46          # square -/+ sim-speed buttons (top-right)
SPEED_LABEL_W = 92      # readout pill between them ("1x", "0.25x", ...)
# Corner-anchored buttons keep a healthy margin from the frame edges: to
# press an edge-hugging button the hand must leave the camera's view, and a
# half-visible hand degrades the landmark model exactly where the user needs
# a clean pinch. ~12% of the frame height keeps the whole hand in frame
# while reaching any button.
EDGE_MARGIN_FRAC = 0.12


class UIManager:
    """Manages all UI state, buttons, and interactable objects."""

    def __init__(self, frame_w, frame_h, gpu_effects=True):
        self.frame_w = frame_w
        self.frame_h = frame_h
        self.state = "menu"
        # False in web mode: the backend never creates a GL context — the
        # browser's WebGL port of the lensing shader renders the black hole
        # from to_state()'s parameters instead.
        self._gpu_effects = gpu_effects
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

        # Always-on pinch cursor (progress ring + click flash) and the
        # optional HALL_DEBUG=1 pipeline HUD.
        self._pinch_cursor = PinchCursor(frame_w, frame_h)
        self._debug_hud = DebugHUD(frame_w, frame_h) if DEBUG_HUD else None

        self._build_buttons()

    def _build_buttons(self):
        fw, fh = self.frame_w, self.frame_h
        margin = int(fh * EDGE_MARGIN_FRAC)

        num_btns = 2
        gap = 16
        total_w = num_btns * MENU_BTN_W + (num_btns - 1) * gap
        start_x = (fw - total_w) // 2
        top_y = margin

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
            x=margin, y=margin, width=120, height=50,
            label="Sphere",
            on_click=self._add_sphere,
        )

        self._sixseven_btn = Button(
            x=margin + 120 + 10, y=margin, width=170, height=50,
            label="6 7 Counter",
            on_click=self._spawn_sixseven,
            font_scale=0.6,
        )

        # Experiment picker: one spawn button per experiment, laid out in a
        # row. Whichever is pressed becomes the single active experiment.
        self._black_hole_btn = Button(
            x=margin, y=margin, width=150, height=50,
            label="Black Hole",
            on_click=self._spawn_black_hole,
        )
        self._slingshot_btn = Button(
            x=margin + 150 + 10, y=margin, width=150, height=50,
            label="Slingshot",
            on_click=self._spawn_slingshot,
        )
        self._experiment_btns = [self._black_hole_btn, self._slingshot_btn]

        # Sim-speed stepper, pinned top-right: [-] 1x [+]. Only shown while
        # the active experiment exposes a `time_scale` (the slingshot).
        plus_x = fw - margin - SPEED_BTN
        label_x = plus_x - SPEED_LABEL_W
        minus_x = label_x - SPEED_BTN
        self._speed_minus_btn = Button(
            x=minus_x, y=margin, width=SPEED_BTN, height=SPEED_BTN,
            label="-",
            on_click=lambda: self._change_sim_speed(-1),
            font_scale=0.9,
        )
        self._speed_plus_btn = Button(
            x=plus_x, y=margin, width=SPEED_BTN, height=SPEED_BTN,
            label="+",
            on_click=lambda: self._change_sim_speed(+1),
            font_scale=0.9,
        )
        self._speed_label_rect = (label_x, margin, SPEED_LABEL_W, SPEED_BTN)

        self._reset_btn = Button(
            x=fw - RESET_W - margin, y=fh - RESET_H - margin,
            width=RESET_W, height=RESET_H,
            label="Reset",
            on_click=self._reset,
        )

    def _set_state(self, new_state):
        self.state = new_state

    def _add_sphere(self):
        self.spheres.append(BouncingSphere(self.frame_w, self.frame_h))

    def _spawn_black_hole(self):
        if self._gpu_effects and self._lensing_renderer is None:
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

    def _speed_control_active(self):
        """True while the active experiment has an adjustable sim speed."""
        return (self.state == "experiments"
                and self._active_experiment is not None
                and hasattr(self._active_experiment, "time_scale"))

    def _change_sim_speed(self, direction):
        exp = self._active_experiment
        if exp is None or not hasattr(exp, "time_scale"):
            return
        if direction > 0:
            exp.speed_up()
        else:
            exp.speed_down()

    def update(self, hand_result, pose_landmarks, hand_received_t=None):
        # Advance every hand's pinch state machine exactly once per frame;
        # buttons and interactables then read the shared snapshot through
        # pinch_state()/pinch_info(). `hand_received_t` (the monotonic
        # instant the detection result arrived) lets the cursor compensate
        # the result's age by velocity extrapolation.
        update_pinches(hand_result, self.frame_w, self.frame_h,
                       received_t=hand_received_t)

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
                if self._speed_control_active():
                    self._speed_minus_btn.update(hand_result, pose_landmarks, self.frame_w, self.frame_h)
                    self._speed_plus_btn.update(hand_result, pose_landmarks, self.frame_w, self.frame_h)
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
            return (self._reset_btn.pressed or self._active_experiment.grabbed
                    or self._speed_minus_btn.pressed or self._speed_plus_btn.pressed)
        return False

    def to_state(self):
        """Serializable UI snapshot for the web frontend.

        Mirrors the per-state branching of draw(): only the buttons/objects
        the cv2 path would draw this frame are included, so the browser is
        a pure renderer of the same scene. All logic (state machine,
        hit-testing, physics) stays here.
        """
        buttons = []
        objects = []
        speed = None
        experiment = None

        if self.state == "menu":
            buttons = [
                self._menu_interactables_btn.to_state("menu.interactables"),
                self._menu_experiments_btn.to_state("menu.experiments"),
            ]

        elif self.state == "interactables":
            buttons = [
                self._sphere_btn.to_state("spawn.sphere"),
                self._sixseven_btn.to_state("spawn.sixseven"),
                self._reset_btn.to_state("reset"),
            ]
            objects = [dict(s.to_state(), id=i)
                       for i, s in enumerate(self.spheres)]
            if self._sixseven is not None:
                objects.append(self._sixseven.to_state())

        elif self.state == "experiments":
            if self._active_experiment is None:
                buttons = [
                    self._black_hole_btn.to_state("exp.black_hole"),
                    self._slingshot_btn.to_state("exp.slingshot"),
                ]
            else:
                exp_state = self._active_experiment.to_state()
                experiment = exp_state["type"]
                objects = [exp_state]
                if self._speed_control_active():
                    buttons = [
                        self._speed_minus_btn.to_state("speed.minus"),
                        self._speed_plus_btn.to_state("speed.plus"),
                    ]
                    x, y, w, h = self._speed_label_rect
                    speed = {"rect": [x, y, w, h],
                             "text": f"{self._active_experiment.time_scale:g}x"}
            buttons.append(self._reset_btn.to_state("reset"))

        return {
            "session": {
                "state": self.state,
                "experiment": experiment,
                "hint": {"visible": self._pinch_hint.visible},
            },
            "buttons": buttons,
            "speed": speed,
            "objects": objects,
        }

    def _draw_speed_label(self, frame):
        """Readout pill between the -/+ buttons showing the sim speed."""
        x, y, w, h = self._speed_label_rect
        cv2.rectangle(frame, (x, y), (x + w, y + h), (30, 30, 30), -1)
        cv2.rectangle(frame, (x, y), (x + w, y + h), (120, 120, 120), 2)
        text = f"{self._active_experiment.time_scale:g}x"
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale, thick = 0.65, 2
        (tw, th), _ = cv2.getTextSize(text, font, scale, thick)
        cv2.putText(frame, text, (x + (w - tw) // 2, y + (h + th) // 2),
                    font, scale, (0, 255, 255), thick, cv2.LINE_AA)

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
                if self._speed_control_active():
                    self._speed_minus_btn.draw(frame)
                    self._speed_plus_btn.draw(frame)
                    self._draw_speed_label(frame)
            else:
                for btn in self._experiment_btns:
                    btn.draw(frame)
            self._reset_btn.draw(frame)

        # The pinch cursor sits above the scene so the user always sees the
        # exact point — and the progress — the detector sees.
        self._pinch_cursor.draw(frame)

        # Onboarding overlays sit on top of the scene. The bottom-right hint
        # yields to the intro splash so they never stack.
        if self._intro.active:
            self._intro.draw(frame)
        else:
            self._pinch_hint.draw(frame)

        # The debug HUD (HALL_DEBUG=1) draws dead-last, above everything.
        if self._debug_hud is not None:
            self._debug_hud.draw(frame)
