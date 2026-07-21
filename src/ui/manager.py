import os

import cv2

from config import (DEBUG_HUD, POSE_ENABLED, QR_BOX_FRAC, QR_DIR,
                    QR_MARGIN_FRAC, START_VTUBER)
from detection.gestures import update_pinches
from rendering.gl_lensing import LensingRenderer
from ui.button import Button
from ui.cursor import PinchCursor
from ui.debug_hud import DebugHUD
from ui.hints import IntroOverlay, PinchHint
from ui.interactables import (BlackHole, BouncingSphere, Charges, Orbitals,
                              Puppet, SchrodingerCat, SixSevenCounter,
                              Slingshot, Spacetime, Waves)

MENU_BTN_W, MENU_BTN_H = 260, 70
RESET_W, RESET_H = 130, 50

# Selectable vtuber avatars — MUST match the order of AVATARS in
# web/src/gl/avatars.ts (the frontend maps this index to the .vrm file). The
# pinch "Avatar" button cycles this list; the index rides to_state() so the
# browser loads the matching model.
AVATAR_NAMES = ["Shino", "Cool Alien", "Cool Banana", "Milk", "Agnes", "Stitch Witch"]
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
        # (a BlackHole, Slingshot, Orbitals, …), or None while its picker is
        # shown. Only one experiment is active at a time.
        self._active_experiment = None
        # QR plate sprites (_experiment_qr): resized per (key, side), key
        # re-read only when the active experiment instance changes.
        self._qr_cache = {}
        self._qr_exp = None
        self._qr_key = None
        self._sixseven = None
        # The vtuber puppet, live only while the user spawns it in the
        # "interactables" state (None otherwise).
        self._puppet = None
        # Vtuber "skeleton view" toggle (web frontend hides the avatar and
        # draws the raw pose+hand inference on the body). Kiosk-accessible via
        # the pinch button below; mirrored to the frontend in to_state().
        self._show_points = False
        # Which vtuber avatar is selected (index into AVATAR_NAMES /
        # web/src/gl/avatars.ts). Cycled by the pinch "Avatar" button; rides
        # to_state() so the frontend loads the matching .vrm.
        self._avatar_index = 0
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

        # Dev: jump straight into the Vtuber scene (drive the avatar from a
        # recorded video instead of live pinches). See config.START_VTUBER.
        if START_VTUBER:
            self.state = "interactables"
            self._spawn_puppet()

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

        self._vtuber_btn = Button(
            x=margin + 120 + 10, y=margin, width=150, height=50,
            label="Rigged Model",
            on_click=self._spawn_puppet,
            font_scale=0.6,
        )

        self._sixseven_btn = Button(
            x=margin + 120 + 10 + 150 + 10, y=margin, width=170, height=50,
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
        self._orbitals_btn = Button(
            x=margin + (150 + 10) * 2, y=margin, width=150, height=50,
            label="Orbitals",
            on_click=self._spawn_orbitals,
        )
        self._waves_btn = Button(
            x=margin + (150 + 10) * 3, y=margin, width=150, height=50,
            label="Waves",
            on_click=self._spawn_waves,
        )
        self._charges_btn = Button(
            x=margin + (150 + 10) * 4, y=margin, width=150, height=50,
            label="Charges",
            on_click=self._spawn_charges,
        )
        self._spacetime_btn = Button(
            x=margin + (150 + 10) * 5, y=margin, width=150, height=50,
            label="Spacetime",
            on_click=self._spawn_spacetime,
            font_scale=0.6,
        )
        self._schrodinger_btn = Button(
            x=margin + (150 + 10) * 6, y=margin, width=150, height=50,
            label="Quantum Cat",
            on_click=self._spawn_schrodinger,
            font_scale=0.6,
        )
        self._experiment_btns = [self._black_hole_btn, self._slingshot_btn,
                                 self._orbitals_btn, self._waves_btn,
                                 self._charges_btn, self._spacetime_btn,
                                 self._schrodinger_btn]

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

        # "Points" toggle (bottom-left, only while the vtuber puppet is live):
        # flips the web skeleton view so the raw inference is visible on the
        # touchless kiosk without a keyboard.
        self._points_btn = Button(
            x=margin, y=fh - RESET_H - margin,
            width=150, height=RESET_H,
            label="Points",
            on_click=self._toggle_points,
            font_scale=0.6,
        )

        # "Avatar" cycler — stacked one row ABOVE Points (bottom-left, only
        # while the vtuber puppet is live). Kept off the frame edge by `margin`
        # (EDGE_MARGIN_FRAC) like every other button, so the pinch lands on a
        # fully-in-frame hand. Label shows the current model; pressing advances.
        self._avatar_btn = Button(
            x=margin, y=fh - RESET_H - margin - RESET_H - 16,
            width=220, height=RESET_H,
            label=f"Avatar: {AVATAR_NAMES[0]}",
            on_click=self._cycle_avatar,
            font_scale=0.6,
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

    def _spawn_orbitals(self):
        self._active_experiment = Orbitals(self.frame_w, self.frame_h)

    def _spawn_waves(self):
        self._active_experiment = Waves(self.frame_w, self.frame_h)

    def _spawn_charges(self):
        self._active_experiment = Charges(self.frame_w, self.frame_h)

    def _spawn_spacetime(self):
        self._active_experiment = Spacetime(self.frame_w, self.frame_h)

    def _spawn_schrodinger(self):
        self._active_experiment = SchrodingerCat(self.frame_w, self.frame_h)

    def _spawn_puppet(self):
        self._puppet = Puppet(self.frame_w, self.frame_h)

    def _toggle_points(self):
        self._show_points = not self._show_points
        self._points_btn.selected = self._show_points

    def _cycle_avatar(self):
        self._avatar_index = (self._avatar_index + 1) % len(AVATAR_NAMES)
        self._avatar_btn.label = f"Avatar: {AVATAR_NAMES[self._avatar_index]}"

    def _spawn_sixseven(self):
        # Re-pressing the button while a counter is active resets the
        # tally — gives users a way to zero the count without leaving the
        # mode (the global Reset button drops the counter entirely).
        self._sixseven = SixSevenCounter(self.frame_w, self.frame_h)

    def _reset(self):
        self.spheres.clear()
        self._active_experiment = None
        self._sixseven = None
        self._puppet = None
        self._show_points = False
        self._points_btn.selected = False
        self.state = "menu"

    def wants_pose(self):
        """True when an active feature needs body-pose inference right now —
        the Vtuber puppet (its arms follow shoulder→elbow→wrist) or the
        pose-driven 6-7 counter. `main.py` runs the pose detector only when
        this (or the HALL_POSE=1 override) is set, so the default hand-only
        UI keeps pose OFF — the big CPU win — while selecting Vtuber lights
        the skeleton up on demand and puts it away again on Reset."""
        return self._puppet is not None or self._sixseven is not None

    def _experiment_palette(self):
        """(id, Button) list the active experiment exposes for its own
        controls (e.g. the Orbitals body-type + preset palette), or empty.
        Lets an experiment own its buttons without the UIManager knowing the
        specific experiment type."""
        exp = self._active_experiment
        return getattr(exp, "palette", []) if exp is not None else []

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

        # Dev lock: keep the puppet alive so a video-driven session can't
        # accidentally Reset itself back to the menu.
        if START_VTUBER and (self._puppet is None or self.state != "interactables"):
            self.state = "interactables"
            if self._puppet is None:
                self._spawn_puppet()

        if self.state == "menu":
            self._menu_interactables_btn.update(hand_result, pose_landmarks, self.frame_w, self.frame_h)
            self._menu_experiments_btn.update(hand_result, pose_landmarks, self.frame_w, self.frame_h)

        elif self.state == "interactables":
            self._sphere_btn.update(hand_result, pose_landmarks, self.frame_w, self.frame_h)
            self._vtuber_btn.update(hand_result, pose_landmarks, self.frame_w, self.frame_h)
            if POSE_ENABLED:
                # The 6-7 counter is pose-driven; without body inference its
                # button would spawn a counter that can never count.
                self._sixseven_btn.update(hand_result, pose_landmarks, self.frame_w, self.frame_h)
            for s in self.spheres:
                s.update(hand_result, pose_landmarks)
            if self._sixseven is not None:
                self._sixseven.update(hand_result, pose_landmarks)
            if self._puppet is not None:
                self._puppet.update(hand_result, pose_landmarks)
                self._points_btn.update(hand_result, pose_landmarks, self.frame_w, self.frame_h)
                self._avatar_btn.update(hand_result, pose_landmarks, self.frame_w, self.frame_h)
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
                for _id, btn in self._experiment_palette():
                    btn.update(hand_result, pose_landmarks, self.frame_w, self.frame_h)
            self._reset_btn.update(hand_result, pose_landmarks, self.frame_w, self.frame_h)

        if self._detect_interaction():
            self._has_interacted = True
        # Person presence for the onboarding hint: pose when available,
        # otherwise any tracked hand (pose is optional since HALL_POSE=0).
        person_detected = pose_landmarks is not None or (
            hand_result is not None and len(hand_result.hand_landmarks) > 0)
        self._pinch_hint.update(person_detected, self._has_interacted)

    def _detect_interaction(self):
        """True on a frame where the user pressed a button or grabbed an
        object — used to retire the onboarding pinch hint."""
        if self.state == "menu":
            return self._menu_interactables_btn.pressed or self._menu_experiments_btn.pressed
        if self.state == "interactables":
            return (self._sphere_btn.pressed or self._vtuber_btn.pressed
                    or self._sixseven_btn.pressed
                    or self._reset_btn.pressed
                    or any(s.grabbed for s in self.spheres)
                    or (self._puppet is not None and (self._puppet.grabbed
                        or self._points_btn.pressed
                        or self._avatar_btn.pressed)))
        if self.state == "experiments":
            if self._active_experiment is None:
                return self._reset_btn.pressed or any(b.pressed for b in self._experiment_btns)
            return (self._reset_btn.pressed or self._active_experiment.grabbed
                    or self._speed_minus_btn.pressed or self._speed_plus_btn.pressed
                    or any(btn.pressed for _id, btn in self._experiment_palette()))
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
            buttons = [self._sphere_btn.to_state("spawn.sphere"),
                       self._vtuber_btn.to_state("spawn.vtuber")]
            if POSE_ENABLED:
                buttons.append(self._sixseven_btn.to_state("spawn.sixseven"))
            buttons.append(self._reset_btn.to_state("reset"))
            objects = [dict(s.to_state(), id=i)
                       for i, s in enumerate(self.spheres)]
            if self._sixseven is not None:
                objects.append(self._sixseven.to_state())
            # The puppet renders last so its dim backdrop sits over the scene.
            if self._puppet is not None:
                objects.append(self._puppet.to_state())
                buttons.append(self._points_btn.to_state("points"))
                buttons.append(self._avatar_btn.to_state("avatar"))

        elif self.state == "experiments":
            if self._active_experiment is None:
                buttons = [
                    self._black_hole_btn.to_state("exp.black_hole"),
                    self._slingshot_btn.to_state("exp.slingshot"),
                    self._orbitals_btn.to_state("exp.orbitals"),
                    self._waves_btn.to_state("exp.waves"),
                    self._charges_btn.to_state("exp.charges"),
                    self._spacetime_btn.to_state("exp.spacetime"),
                    self._schrodinger_btn.to_state("exp.schrodinger"),
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
                # Experiment-owned palette buttons (e.g. Orbitals body types).
                for _id, btn in self._experiment_palette():
                    buttons.append(btn.to_state(_id))
            buttons.append(self._reset_btn.to_state("reset"))

        return {
            "session": {
                "state": self.state,
                "experiment": experiment,
                "hint": {"visible": self._pinch_hint.visible},
                # Web-only: hide the avatar + draw the raw pose/hand skeleton.
                "show_points": self._show_points,
                # Which vtuber avatar the frontend should load (index into
                # web/src/gl/avatars.ts). Cycled by the "Avatar" pinch button.
                "avatar_index": self._avatar_index,
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

    def _experiment_qr(self, side):
        """QR sprite for the active experiment, resized to `side` px square,
        or None (missing PNG → the caller keeps the dashed placeholder).
        The experiment key is read once per activation via to_state()["type"]
        (== session.experiment); the resized sprite is cached per (key, side)
        like _scat_sprite — the plate redraws every frame."""
        exp = self._active_experiment
        if exp is not self._qr_exp:
            self._qr_exp = exp
            self._qr_key = None if exp is None else exp.to_state()["type"]
        if self._qr_key is None:
            return None
        key = (self._qr_key, side)
        if key not in self._qr_cache:
            img = cv2.imread(os.path.join(QR_DIR, self._qr_key + ".png"))
            self._qr_cache[key] = None if img is None else cv2.resize(
                img, (side, side), interpolation=cv2.INTER_AREA)
        return self._qr_cache[key]

    def _draw_qr_plate(self, frame):
        """White plate bottom-left of every RUNNING experiment carrying its
        QR code — the link to the experiment's page on the exhibit site
        (web/scripts/gen_qr.py renders the codes into QR_DIR). The plate's
        white padding doubles as the QR quiet zone. Falls back to the dashed
        "QR" placeholder when the PNG is missing. Geometry mirrored by hand
        in web/src/overlay/scene.ts (drawQrPlate)."""
        side = int(self.frame_h * QR_BOX_FRAC)
        m = int(self.frame_h * QR_MARGIN_FRAC)
        x0, y0 = m, self.frame_h - m - side
        cv2.rectangle(frame, (x0, y0), (x0 + side, y0 + side),
                      (255, 255, 255), -1)
        cv2.rectangle(frame, (x0, y0), (x0 + side, y0 + side),
                      (60, 60, 60), 2)
        # Keep in sync with scene.ts: pad 0.06·side + the PNG's own 2-module
        # border ≈ the 4-module ISO quiet zone at plate scale.
        qpad = int(side * 0.06)
        qr = self._experiment_qr(side - 2 * qpad)
        if qr is not None:
            frame[y0 + qpad:y0 + qpad + qr.shape[0],
                  x0 + qpad:x0 + qpad + qr.shape[1]] = qr
            return
        # Dashed inner square (cv2 has no dash pattern: short segments).
        pad = int(side * 0.12)
        ix0, iy0, ix1, iy1 = x0 + pad, y0 + pad, x0 + side - pad, y0 + side - pad
        gray = (168, 160, 150)
        for a in range(ix0, ix1, 13):
            b = min(a + 7, ix1)
            cv2.line(frame, (a, iy0), (b, iy0), gray, 2)
            cv2.line(frame, (a, iy1), (b, iy1), gray, 2)
        for a in range(iy0, iy1, 13):
            b = min(a + 7, iy1)
            cv2.line(frame, (ix0, a), (ix0, b), gray, 2)
            cv2.line(frame, (ix1, a), (ix1, b), gray, 2)
        scale = side / 110.0
        (tw, th), _ = cv2.getTextSize("QR", cv2.FONT_HERSHEY_SIMPLEX,
                                      scale, 2)
        cv2.putText(frame, "QR", (x0 + (side - tw) // 2,
                    y0 + (side + th) // 2), cv2.FONT_HERSHEY_SIMPLEX,
                    scale, (122, 128, 136), 2, cv2.LINE_AA)

    def draw(self, frame):
        if self.state == "menu":
            self._menu_interactables_btn.draw(frame)
            self._menu_experiments_btn.draw(frame)

        elif self.state == "interactables":
            self._sphere_btn.draw(frame)
            self._vtuber_btn.draw(frame)
            if POSE_ENABLED:
                self._sixseven_btn.draw(frame)
            for s in self.spheres:
                s.draw(frame)
            if self._sixseven is not None:
                self._sixseven.draw(frame)
            # The puppet dims the scene, so it draws over the spheres.
            if self._puppet is not None:
                self._puppet.draw(frame)
                self._points_btn.draw(frame)
                self._avatar_btn.draw(frame)
            self._reset_btn.draw(frame)

        elif self.state == "experiments":
            # The active experiment draws first (e.g. the BH's full-frame
            # distortion) so the picker/reset buttons stay readable on top.
            if self._active_experiment is not None:
                self._active_experiment.draw(frame)
                self._draw_qr_plate(frame)
                if self._speed_control_active():
                    self._speed_minus_btn.draw(frame)
                    self._speed_plus_btn.draw(frame)
                    self._draw_speed_label(frame)
                for _id, btn in self._experiment_palette():
                    btn.draw(frame)
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
