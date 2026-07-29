import os
import time

import cv2

from config import (ATTRACT_ENABLED, ATTRACT_IDLE_S, DEBUG_HUD, DEMO_GESTURE,
                    GESTURE_MODE, HINT_TEXT, QR_BOX_FRAC, QR_DIR,
                    QR_MARGIN_FRAC, START_VTUBER)
from detection.gestures import (hand_id, pinch_info, pinch_infos, reserve_hand,
                                update_pinches)
from rendering.gl_lensing import LensingRenderer
from ui.attract import AttractScreen, Greeting
from ui.button import Button
from ui.cursor import PinchCursor
from ui.debug_hud import DebugHUD
from ui.gallery import Gallery
from ui.hints import GestureHint, IntroOverlay
from ui.interactables import (BlackHole, BouncingSphere, Charges, Magnets,
                              Orbitals, Puppet, SchrodingerCat,
                              SixSevenCounter, Slingshot, Spacetime, Waves)
from ui.presence import PresenceDetector

MENU_BTN_W, MENU_BTN_H = 260, 70
RESET_W, RESET_H = 130, 50

# Selectable vtuber avatars — MUST match the order of AVATARS in
# web/src/gl/avatars.ts (the frontend maps this index to the .vrm file). The
# pinch "Avatar" button cycles this list; the index rides to_state() so the
# browser loads the matching model.
AVATAR_NAMES = ["Cool Alien", "Cool Banana", "Milk", "Agnes", "Stitch Witch"]
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
        # Attract phase, one level ABOVE `state`: "attract" (nobody there,
        # slideshow), "greeting" (somebody just arrived, being shown the
        # gesture) or "live" (`state` means something). Kept separate so
        # every existing state/button/scene branch below is untouched — the
        # exhibit's idle behaviour is a wrapper around the app, not a mode
        # inside it. HALL_ATTRACT=0 pins it to "live" forever.
        self.phase = "attract" if ATTRACT_ENABLED else "live"
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
        # The photo gallery, live only while `state == "gallery"`. Built on
        # entry rather than at boot so it re-reads the gallery folder each
        # time somebody opens it — a photograph copied onto the device shows
        # up for the next visitor without a restart.
        self._gallery = None
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

        # Onboarding overlays. The bottom-right hint shows until the user
        # first interacts. The startup splash exists only when attract mode
        # is OFF: with it on, the greeting is a better version of the same
        # thing — it plays for each visitor instead of once per boot, which
        # nobody but the person who turned the exhibit on would ever see.
        self._intro = None if ATTRACT_ENABLED else IntroOverlay(frame_w,
                                                                frame_h)
        self._pinch_hint = GestureHint(frame_w, frame_h)
        self._has_interacted = False

        # Attract mode: is anybody there, and what to show while nobody is.
        self._presence = PresenceDetector()
        self._attract = AttractScreen(frame_w, frame_h)
        self._greeting = Greeting(frame_w, frame_h)
        # When presence was last seen. Absence has to persist for
        # ATTRACT_IDLE_S before the exhibit gives up on the current visitor,
        # so stepping out of frame to fetch a friend does not reset it.
        self._last_present_t = time.monotonic()

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

        num_btns = 3
        gap = 16
        total_w = num_btns * MENU_BTN_W + (num_btns - 1) * gap
        start_x = (fw - total_w) // 2
        top_y = margin

        self._menu_interactables_btn = Button(
            x=start_x, y=top_y,
            width=MENU_BTN_W, height=MENU_BTN_H,
            label="Games",
            on_click=lambda: self._set_state("interactables"),
        )
        self._menu_experiments_btn = Button(
            x=start_x + MENU_BTN_W + gap, y=top_y,
            width=MENU_BTN_W, height=MENU_BTN_H,
            label="Experiments",
            on_click=lambda: self._set_state("experiments"),
        )
        self._menu_gallery_btn = Button(
            x=start_x + (MENU_BTN_W + gap) * 2, y=top_y,
            width=MENU_BTN_W, height=MENU_BTN_H,
            label="Gallery",
            on_click=self._open_gallery,
        )

        # Gallery Prev/Next, centred under the card. Kept well inside the
        # frame (EDGE_MARGIN_FRAC) like every other pinch target, and clear
        # of the card itself so pressing one is never mistaken for grabbing
        # the strip — the hand reservation already guarantees they cannot
        # both fire, but overlapping them would still look wrong.
        nav_w, nav_h = 120, 54
        nav_y = fh - margin - nav_h
        self._gallery_prev_btn = Button(
            x=fw // 2 - nav_w - 20, y=nav_y, width=nav_w, height=nav_h,
            label="< Prev",
            on_click=lambda: self._step_gallery(-1),
        )
        self._gallery_next_btn = Button(
            x=fw // 2 + 20, y=nav_y, width=nav_w, height=nav_h,
            label="Next >",
            on_click=lambda: self._step_gallery(+1),
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
        # 8th experiment wraps to a second row: at the kiosk's 1280 px the
        # first row is full (7 buttons end at ~1196 px).
        self._magnets_btn = Button(
            x=margin, y=margin + 50 + 10, width=150, height=50,
            label="Magnets",
            on_click=self._spawn_magnets,
        )
        # (state id, Button) like every other list the manager hands around —
        # see _active_buttons().
        self._experiment_btns = [
            ("exp.black_hole", self._black_hole_btn),
            ("exp.slingshot", self._slingshot_btn),
            ("exp.orbitals", self._orbitals_btn),
            ("exp.waves", self._waves_btn),
            ("exp.charges", self._charges_btn),
            ("exp.spacetime", self._spacetime_btn),
            ("exp.schrodinger", self._schrodinger_btn),
            ("exp.magnets", self._magnets_btn),
        ]

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

    def _open_gallery(self):
        # Rebuilt on every entry, so it re-reads the gallery folder: a
        # photograph copied onto the device is browsable for the next
        # visitor without restarting the kiosk.
        self._gallery = Gallery(self.frame_w, self.frame_h)
        self._set_state("gallery")

    def _step_gallery(self, delta):
        if self._gallery is not None:
            self._gallery.step(delta)

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

    def _spawn_magnets(self):
        self._active_experiment = Magnets(self.frame_w, self.frame_h)

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
        self._gallery = None
        self._puppet = None
        self._show_points = False
        self._points_btn.selected = False
        self.state = "menu"

    # --- attract phase ----------------------------------------------------

    def _enter_greeting(self, now):
        """Somebody just walked up: hand them a clean exhibit and say hi.

        The reset is the point. Without it every visitor inherits whatever
        the last one abandoned — a dragged black hole, a menu three levels
        deep — and has no idea it is not the exhibit's normal state. The
        onboarding hint is rebuilt too, since it retires after ONE person
        interacts and the next person has not.
        """
        self._reset()
        self._has_interacted = False
        self._pinch_hint = GestureHint(self.frame_w, self.frame_h)
        self._greeting.enter(now)
        self.phase = "greeting"

    def _enter_attract(self, now):
        self._reset()
        self._attract.enter(now)
        self.phase = "attract"

    def _gesture_fired(self):
        """True on a frame where any hand completed a closing gesture."""
        return any(m.pinching for _hid, m in pinch_infos())

    def _update_phase(self, hand_result, pose_landmarks, frame):
        """Advance attract -> greeting -> live -> attract."""
        if not ATTRACT_ENABLED or START_VTUBER:
            self.phase = "live"
            return

        now = time.monotonic()
        if self._presence.update(frame, hand_result, pose_landmarks, now):
            self._last_present_t = now

        if self.phase == "attract":
            if self._presence.present:
                self._enter_greeting(now)
        elif self.phase == "greeting":
            # Making the gesture is a better way out than waiting for a bar
            # to fill: a visitor who has already understood the instruction
            # should not be held at it. Buttons are not updated during the
            # greeting, so the same gesture cannot also press something.
            if self._greeting.done(now) or self._gesture_fired():
                self.phase = "live"
        elif now - self._last_present_t > ATTRACT_IDLE_S:
            self._enter_attract(now)

    def presence_state(self):
        """What the presence detector currently sees — debug-block payload.

        Exposed as a method so `web/state.py` does not reach into the
        manager's internals for it (the debug HUD is the only consumer).
        """
        return self._presence.to_state()

    def presence_blob_rect(self):
        """Normalized box of the largest moving thing, or None.

        `auto_exposure` meters on this when the hand detector has nothing:
        against a window a visitor is a silhouette no landmark model can find,
        while a difference image sees them regardless of how dark they are.
        Same reason it is a method rather than a public attribute as
        `presence_state`.
        """
        return self._presence.blob_rect

    def wants_pose(self):
        """True when an active feature needs body-pose inference right now —
        which is the Vtuber puppet alone (its arms follow
        shoulder→elbow→wrist). `main.py` runs the pose detector only when
        this (or the HALL_POSE=1 override) is set, so the default hand-only
        UI keeps pose OFF — the big CPU win — while selecting Vtuber lights
        the skeleton up on demand and puts it away again on Reset.

        The 6-7 counter used to be listed here too. It is hand-only now (see
        `SixSevenCounter`), which matters beyond the CPU: building the pose
        detector happens INSIDE the render loop, and on the Jetson that is a
        multi-second TensorRT engine load — a freeze the whole exhibit would
        have paid the first time any visitor opened the game."""
        return self._puppet is not None

    def _experiment_palette(self):
        """(id, Button) list the active experiment exposes for its own
        controls (e.g. the Orbitals body-type + preset palette), or empty.
        Lets an experiment own its buttons without the UIManager knowing the
        specific experiment type."""
        exp = self._active_experiment
        return getattr(exp, "palette", []) if exp is not None else []

    def _active_buttons(self):
        """The ``(state id, Button)`` pairs live this frame.

        The single source for the four things done with them — updating,
        reserving the hands over them, serializing them and drawing them.
        Three hand-kept copies of this list used to exist (`update`,
        `to_state`, `draw`); the reservation below wanted a fourth, and a
        button that is drawn but never updated (or hit-tested but never
        shown) is exactly the bug that invites.
        """
        if self.phase != "live":
            return []

        if self.state == "menu":
            return [("menu.interactables", self._menu_interactables_btn),
                    ("menu.experiments", self._menu_experiments_btn),
                    ("menu.gallery", self._menu_gallery_btn)]

        if self.state == "gallery":
            # Prev/Next are the discoverable half of the navigation; the drag
            # is the good half. Both are live at once and cannot collide,
            # since a hand over either button is reserved before the gallery
            # is updated (see _reserve_ui_hands).
            return [("gallery.prev", self._gallery_prev_btn),
                    ("gallery.next", self._gallery_next_btn),
                    ("reset", self._reset_btn)]

        if self.state == "interactables":
            # The 6-7 counter is pose-driven, and this button used to be
            # hidden unless HALL_POSE=1 — which is 0 on the exhibit, so the
            # game was unreachable there. The gate was never needed:
            # `wants_pose()` reports the live counter and `main.py` builds
            # body inference on demand for it, exactly as it does for the
            # Vtuber (which was never gated). Spawning costs a one-time
            # model-load hitch; Reset puts pose away again.
            out = [("spawn.sphere", self._sphere_btn),
                   ("spawn.vtuber", self._vtuber_btn),
                   ("spawn.sixseven", self._sixseven_btn)]
            if self._puppet is not None:
                out.append(("points", self._points_btn))
                out.append(("avatar", self._avatar_btn))
            out.append(("reset", self._reset_btn))
            return out

        if self.state == "experiments":
            if self._active_experiment is None:
                out = list(self._experiment_btns)
            else:
                out = []
                if self._speed_control_active():
                    out.append(("speed.minus", self._speed_minus_btn))
                    out.append(("speed.plus", self._speed_plus_btn))
                # Experiment-owned palette (e.g. Orbitals body types).
                out.extend(self._experiment_palette())
            out.append(("reset", self._reset_btn))
            return out

        return []

    def _reserve_ui_hands(self, buttons, hand_result):
        """Give each button ownership of the hands sitting over it.

        Buttons float ON TOP of the scene, and the two read the same pinch
        snapshot independently — so closing your hand on "Magnets" pressed
        the button *and* dropped a magnet underneath it, and merely hovering
        a button while pinching planted objects behind it. Reserving the
        hand makes the topmost thing win, the way a click on a dialog does
        not also reach the page behind it.

        Reserved on HOVER, not on the press, because both halves of the
        complaint matter: nothing should appear under a button whether or
        not the click lands. Both cursors are tested — the live one covers
        hovering, and the press-latched one covers a close that BEGAN
        outside and ended over the button (the button ignores that click,
        so the scene must not take it either).

        Only the closing EVENT is withheld (see ``gestures.pinch_state``);
        a drag already under way keeps its hold, so carrying a charge past
        the Reset button does not drop it there.
        """
        if hand_result is None or not buttons:
            return
        for i in range(len(hand_result.hand_landmarks)):
            hid = hand_id(hand_result, i)
            info = pinch_info(hid)
            if info is None:
                continue
            if any(btn.covers(info.cursor) or btn.covers(info.press_cursor)
                   for _bid, btn in buttons):
                reserve_hand(hid)

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

    def update(self, hand_result, pose_landmarks, hand_received_t=None,
               frame=None):
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

        # `frame` (the mirrored camera image) is the motion signal presence
        # runs on; it is optional so a caller without one still gets the
        # hand/pose signals.
        self._update_phase(hand_result, pose_landmarks, frame)
        if self.phase != "live":
            # Nothing below is reachable without a visitor: no buttons to
            # press, no scene to step. Hide the onboarding hint so it does
            # not surface over the slideshow or the greeting.
            self._pinch_hint.update(False, self._has_interacted)
            return

        # BUTTONS FIRST, then the hands over them are reserved, then the
        # scene. The order is the fix for "pressing a button also spawned
        # something behind it": buttons sit on top, so they get first refusal
        # on every closing gesture, and the scene is told which hands are
        # already spoken for before it looks at any of them.
        buttons = self._active_buttons()
        for _bid, btn in buttons:
            btn.update(hand_result, pose_landmarks, self.frame_w,
                       self.frame_h)
        self._reserve_ui_hands(buttons, hand_result)

        if self.state == "interactables":
            for s in self.spheres:
                s.update(hand_result, pose_landmarks)
            if self._sixseven is not None:
                self._sixseven.update(hand_result, pose_landmarks)
            if self._puppet is not None:
                self._puppet.update(hand_result, pose_landmarks)

        elif self.state == "experiments":
            if self._active_experiment is not None:
                self._active_experiment.update(hand_result, pose_landmarks)

        elif self.state == "gallery":
            if self._gallery is not None:
                self._gallery.update(hand_result, pose_landmarks)

        if self._detect_interaction():
            self._has_interacted = True
        # Person presence for the onboarding hint: pose when available,
        # otherwise any tracked hand (pose is optional since HALL_POSE=0).
        person_detected = pose_landmarks is not None or (
            hand_result is not None and len(hand_result.hand_landmarks) > 0)
        self._pinch_hint.update(person_detected, self._has_interacted)

    def _detect_interaction(self):
        """True on a frame where the user pressed a button or grabbed an
        object — used to retire the onboarding gesture hint."""
        if any(btn.pressed for _bid, btn in self._active_buttons()):
            return True
        if self.state == "interactables":
            return (any(s.grabbed for s in self.spheres)
                    or (self._puppet is not None and self._puppet.grabbed))
        if self.state == "experiments":
            return (self._active_experiment is not None
                    and self._active_experiment.grabbed)
        if self.state == "gallery":
            return self._gallery is not None and self._gallery.grabbed
        return False

    def to_state(self):
        """Serializable UI snapshot for the web frontend.

        Buttons come from the same `_active_buttons()` list that update(),
        the hand reservation and draw() use, so the browser can never be
        sent a button the backend is not hit-testing. Objects still branch
        per state below. All logic (state machine, hit-testing, physics)
        stays here.
        """
        objects = []
        speed = None
        experiment = None

        if self.phase != "live":
            # Nobody to press anything: the browser renders the slideshow or
            # the greeting from `session` alone, and the live UI stays gone
            # rather than sitting greyed out behind it.
            return {"session": self._session_state(None), "buttons": [],
                    "speed": None, "objects": []}

        buttons = [btn.to_state(bid) for bid, btn in self._active_buttons()]

        if self.state == "interactables":
            objects = [dict(s.to_state(), id=i)
                       for i, s in enumerate(self.spheres)]
            if self._sixseven is not None:
                objects.append(self._sixseven.to_state())
            # The puppet renders last so its dim backdrop sits over the scene.
            if self._puppet is not None:
                objects.append(self._puppet.to_state())

        elif self.state == "gallery" and self._gallery is not None:
            objects = [self._gallery.to_state()]

        elif self.state == "experiments" and self._active_experiment is not None:
            exp_state = self._active_experiment.to_state()
            experiment = exp_state["type"]
            objects = [exp_state]
            if self._speed_control_active():
                x, y, w, h = self._speed_label_rect
                speed = {"rect": [x, y, w, h],
                         "text": f"{self._active_experiment.time_scale:g}x"}

        return {
            "session": self._session_state(experiment),
            "buttons": buttons,
            "speed": speed,
            "objects": objects,
        }

    def _session_state(self, experiment):
        """The `session` block, identical in shape across every phase."""
        return {
            "state": self.state,
            "experiment": experiment,
            # Attract phase — "attract", "greeting" or "live". The two
            # payloads below are non-null only in their own phase, so an
            # idle exhibit's state document stays a few hundred bytes.
            "phase": self.phase,
            "attract": (self._attract.to_state()
                        if self.phase == "attract" else None),
            "greeting": (self._greeting.to_state()
                         if self.phase == "greeting" else None),
            # Which gesture closes the cursor (HALL_GESTURE), and which one
            # the onboarding hands should act out. The browser draws its demo
            # from these, so the picture cannot disagree with the detector.
            "gesture": GESTURE_MODE,
            "demo_gesture": DEMO_GESTURE,
            # The words next to the demo hand travel with it, so the
            # browser never hardcodes a sentence about pinching while
            # the detector is watching for a fist.
            "hint": {"visible": self._pinch_hint.visible,
                     "text": HINT_TEXT},
            # Web-only: hide the avatar + draw the raw pose/hand skeleton.
            "show_points": self._show_points,
            # Which vtuber avatar the frontend should load (index into
            # web/src/gl/avatars.ts). Cycled by the "Avatar" pinch button.
            "avatar_index": self._avatar_index,
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
        if self.phase == "attract":
            # The slideshow REPLACES the camera image — see ui/attract.py.
            self._attract.draw(frame)
            if self._debug_hud is not None:
                self._debug_hud.draw(frame, self.presence_state())
            return

        # The SCENE draws first, buttons last: they float on top, they stay
        # readable over a black hole's full-frame distortion, and drawing
        # them last is the visual half of the same rule the hand reservation
        # enforces for input (see _reserve_ui_hands).
        if self.state == "interactables":
            for s in self.spheres:
                s.draw(frame)
            if self._sixseven is not None:
                self._sixseven.draw(frame)
            # The puppet dims the scene, so it draws over the spheres.
            if self._puppet is not None:
                self._puppet.draw(frame)

        elif self.state == "experiments":
            if self._active_experiment is not None:
                self._active_experiment.draw(frame)
                self._draw_qr_plate(frame)

        elif self.state == "gallery":
            if self._gallery is not None:
                self._gallery.draw(frame)

        for _bid, btn in self._active_buttons():
            btn.draw(frame)
        if self.state == "experiments" and self._speed_control_active():
            self._draw_speed_label(frame)

        # The pinch cursor sits above the scene so the user always sees the
        # exact point — and the progress — the detector sees.
        self._pinch_cursor.draw(frame)

        # Onboarding overlays sit on top of the scene, one at a time. The
        # greeting outranks both: it is the one a visitor is actually looking
        # at, and it draws over the live menu appearing behind it.
        if self.phase == "greeting":
            self._greeting.draw(frame)
        elif self._intro is not None and self._intro.active:
            self._intro.draw(frame)
        else:
            self._pinch_hint.draw(frame)

        # The debug HUD (HALL_DEBUG=1) draws dead-last, above everything.
        if self._debug_hud is not None:
            self._debug_hud.draw(frame, self.presence_state())
