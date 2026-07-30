"""Mock HalLMediaPipe backend for frontend development without a camera.

Serves the same contract as `src/output.WebSink` — `/stream.mjpg` (a
synthetic test-card frame), `/state` (SSE, animated scenes) and `/healthz`
— so every UI state can be exercised deterministically, no gestures needed.

Run from the repo root (needs the repo venv for cv2/numpy):

    uv run python web/scripts/mock_backend.py [scene]

Scenes: menu (default), attract, greeting, gallery, slingshot, blackhole,
picker, orbitals, orbaim, waves, charges, magnets, spacetime, schrodinger.
Then point the vite dev server at it:  npm run dev  (same port 8092).
"""

import json
import math
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, unquote

import cv2
import numpy as np

W, H = 1280, 720
PORT = 8092
SCENE = sys.argv[1] if len(sys.argv) > 1 else "menu"

# Mirrors config.GESTURE_MODE / DEMO_GESTURE / HINT_TEXT, so the onboarding
# hands the mock renders are the ones the real backend would ask for. Set
# HALL_GESTURE=pinch here too to preview the other demo hand.
GESTURE = os.environ.get("HALL_GESTURE", "either")
DEMO_GESTURE = "pinch" if GESTURE == "pinch" else "fist"
HINT_TEXT = ("Pinch your fingers to interact" if DEMO_GESTURE == "pinch"
             else "Close your hand to interact")

# Attract slides. Served straight off disk by this mock's /attract/ route,
# the same path the real WebSink serves them from.
#
# HALL_ATTRACT_DIR points this at a real gallery folder, which is how you
# preview the many-photographs case (counter instead of dots, no captions)
# without a camera or a Jetson:
#   HALL_ATTRACT_DIR=~/Pictures/hall uv run python web/scripts/mock_backend.py attract
ATTRACT_DIR = os.path.expanduser(os.environ["HALL_ATTRACT_DIR"]) \
    if os.environ.get("HALL_ATTRACT_DIR") else os.path.join(
        os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))), "docs", "img")
_SLIDE_TEXT = {
    "black_hole": ("Black Hole",
                   "Light bends around a mass so dense it has no surface"),
    "slingshot": ("Slingshot",
                  "Pull, aim, release — gravity and drag do the rest"),
    "orbitals": ("Orbitals",
                 "Launch worlds and watch gravity pull them into orbit"),
    "waves": ("Waves", "Drop sources in a ripple tank and interfere them"),
    "charges": ("Charges",
                "Place charges and see the electric field they make"),
    "magnets": ("Magnets", "Move a magnet through a coil and light a bulb"),
    "spacetime": ("Spacetime",
                  "Mass curves the sheet that everything else falls along"),
    "schrodinger": ("Quantum Cat",
                    "Measure the atom and the cat stops being both"),
}
ATTRACT_SLIDES = [
    # An untitled slide is the gallery case, matching ui/attract.py: only the
    # eight experiment stills have text, camera filenames get none.
    {"src": "/attract/" + quote(name),
     "title": _SLIDE_TEXT.get(os.path.splitext(name)[0], ("", ""))[0],
     "caption": _SLIDE_TEXT.get(os.path.splitext(name)[0], ("", ""))[1]}
    for name in sorted(os.listdir(ATTRACT_DIR))
    if name.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
] if os.path.isdir(ATTRACT_DIR) else []
# spacetime: set HALL_MOCK_YAW=0 to freeze the camera at the default view.
MOCK_YAW = os.environ.get("HALL_MOCK_YAW", "1") == "1"

START = time.monotonic()


def _bg_photo():
    """HALL_MOCK_BG=<image path>: use a real photograph as the fake camera
    frame (cover-cropped to WxH). HALL_MOCK_BG_ALPHA (default 0.85) sets
    the photo's opacity over the site's dark navy, so the overlays stay
    the protagonists. Used for the exhibit-site screenshots, where the
    synthetic test card would look wrong; e.g. NASA's public-domain Webb
    "Cosmic Cliffs" (images-assets.nasa.gov/image/carina_nebula). Returns
    None to fall back to the synthetic card."""
    path = os.environ.get("HALL_MOCK_BG")
    if not path:
        return None
    img = cv2.imread(path)
    if img is None:
        print(f"HALL_MOCK_BG: cannot read {path}; using the test card")
        return None
    ih, iw = img.shape[:2]
    s = max(W / iw, H / ih)
    img = cv2.resize(img, (int(round(iw * s)), int(round(ih * s))),
                     interpolation=cv2.INTER_AREA)
    y0 = (img.shape[0] - H) // 2
    x0 = (img.shape[1] - W) // 2
    alpha = float(os.environ.get("HALL_MOCK_BG_ALPHA", "0.85"))
    navy = np.array([36, 23, 10], np.float32)  # docs/ --navy #0A1724 (BGR)
    crop = img[y0:y0 + H, x0:x0 + W].astype(np.float32)
    return (crop * alpha + navy * (1.0 - alpha)).astype(np.uint8)


def test_card():
    """Synthetic background: gradient + grid + circles — enough structure
    to judge overlays and (crucially) the black-hole lensing distortion.
    HALL_MOCK_BG swaps it for a real photo (see _bg_photo)."""
    photo = _bg_photo()
    if photo is not None:
        frame = photo
        if os.environ.get("HALL_MOCK_LABEL", "1") == "1":
            cv2.putText(frame, "MOCK", (W // 2 - 90, H - 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.6, (230, 230, 230), 3)
        ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
        assert ok
        return jpg.tobytes()
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    frame = np.zeros((H, W, 3), np.uint8)
    frame[..., 0] = (40 + 60 * xx / W).astype(np.uint8)   # B
    frame[..., 1] = (60 + 50 * yy / H).astype(np.uint8)   # G
    frame[..., 2] = (70 + 40 * (1 - xx / W)).astype(np.uint8)  # R
    for x in range(0, W, 80):
        cv2.line(frame, (x, 0), (x, H), (110, 110, 110), 1)
    for y in range(0, H, 80):
        cv2.line(frame, (0, y), (W, y), (110, 110, 110), 1)
    for cx, cy, r, col in [(200, 180, 60, (60, 160, 240)),
                           (1050, 520, 90, (200, 180, 60)),
                           (700, 300, 40, (90, 220, 130))]:
        cv2.circle(frame, (cx, cy), r, col, -1)
        cv2.circle(frame, (cx, cy), r, (240, 240, 240), 2)
    # HALL_MOCK_LABEL=0 hides the watermark — for screenshots that feed the
    # exhibit website (docs/), where a "MOCK" stamp would read as an error.
    if os.environ.get("HALL_MOCK_LABEL", "1") == "1":
        cv2.putText(frame, "MOCK", (W // 2 - 90, H - 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.6, (230, 230, 230), 3)
    ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    assert ok
    return jpg.tobytes()


JPG = test_card()


def btn(bid, label, x, y, w, h, hovered=False, pressed=False):
    return {"id": bid, "label": label, "rect": [x, y, w, h],
            "hovered": hovered, "pressed": pressed}


def fake_hand(t):
    """One hand circling the centre; pinch progress cycles ~2 s."""
    cx = W / 2 + 260 * math.cos(t * 0.9)
    cy = H / 2 + 160 * math.sin(t * 0.9)
    phase = (t % 2.0) / 2.0
    progress = 0.5 * (1 - math.cos(2 * math.pi * phase))
    held = progress > 0.9
    return {
        "id": "Right", "cursor": [round(cx, 1), round(cy, 1)],
        "press_cursor": [round(cx, 1), round(cy, 1)],
        "state": "closed" if held else ("closing" if progress > 0.1 else "open"),
        "progress": round(progress, 3), "ratio": round(0.9 - 0.45 * progress, 3),
        "pinching": 0.88 < progress < 0.92,
        "held": held, "seen_ms": 0.0, "landmarks": None,
    }


def scene_state(t):
    margin = int(H * 0.12)
    hover = int(t) % 2 == 0
    base = {
        "session": {"state": "menu", "experiment": None, "phase": "live",
                    "attract": None, "greeting": None,
                    "gesture": GESTURE, "demo_gesture": DEMO_GESTURE,
                    "hint": {"visible": False, "text": HINT_TEXT}},
        "buttons": [], "speed": None, "objects": [],
    }

    if SCENE == "attract":
        # The idle exhibit. Slides advance on the mock's own clock at the
        # real ATTRACT_SLIDE_S / ATTRACT_FADE_S, so the cross-fade can be
        # judged without waiting out a 30 s absence in front of a camera.
        slide_s, fade_s = 6.5, 1.2
        n = max(len(ATTRACT_SLIDES), 1)
        index = int(t // slide_s) % n
        into = t % slide_s
        faded = into >= fade_s or t < slide_s
        prev = index if faded else (index - 1) % n

        def _slide(i):
            return ATTRACT_SLIDES[i % n] if ATTRACT_SLIDES else None

        base["session"]["phase"] = "attract"
        # Same three-slide window the real backend sends — see
        # AttractScreen.to_state(); the full list never rides the payload.
        base["session"]["attract"] = {
            "title": "Physics and Engineering Life",   # config.ATTRACT_TITLE
            "prompt": "Step closer to control this display with your hand",
            "index": index,
            "count": len(ATTRACT_SLIDES),
            "fade": 1.0 if faded else round(into / fade_s, 3),
            "current": _slide(index),
            "previous": None if prev == index else _slide(prev),
            "next": _slide(index + 1) if len(ATTRACT_SLIDES) > 1 else None,
        }

    elif SCENE == "greeting":
        base["session"]["phase"] = "greeting"
        base["session"]["greeting"] = {
            "title": "Hi",
            "subtitle": "This display is controlled with your hand",
            "hint": HINT_TEXT,
            "t": round(t % 5.0, 2),
            "duration": 5.0,
        }

    elif SCENE == "menu":
        bw, bh, gap = 260, 70, 16
        sx = (W - 2 * bw - gap) // 2
        base["buttons"] = [
            btn("menu.experiments", "Experiments", sx, margin, bw, bh,
                hovered=hover),
            btn("menu.gallery", "Gallery", sx + bw + gap, margin, bw, bh),
        ]
        base["session"]["hint"] = {"visible": True}

    elif SCENE == "gallery":
        # The photo strip, scrolled continuously so the card layout, the
        # neighbours peeking in and the caption row can all be judged in one
        # screenshot. Geometry mirrors ui/gallery.py's card_rect.
        base["session"]["state"] = "gallery"
        n = max(len(ATTRACT_SLIDES), 1)
        card_h = int(round(H * 0.60))
        card_w = min(int(round(card_h * 16 / 9)), int(round(W * 0.62)))
        card_h = int(round(card_w / (16 / 9)))
        card_x, card_y = (W - card_w) // 2, int(round(H * 0.10))
        stride = card_w + int(round(W * 0.035))
        position = (t * 0.35) % n
        index = int(round(position)) % n
        lo, hi = max(index - 2, 0), min(index + 2, n - 1)
        nav_w, nav_h = 120, 54
        base["buttons"] = [
            btn("gallery.prev", "< Prev", W // 2 - nav_w - 20,
                H - margin - nav_h, nav_w, nav_h),
            btn("gallery.next", "Next >", W // 2 + 20, H - margin - nav_h,
                nav_w, nav_h),
            btn("reset", "Reset", W - 130 - margin, H - 50 - margin, 130, 50),
        ]
        base["objects"] = [{
            "type": "gallery",
            "index": index,
            "position": round(position, 3),
            "count": len(ATTRACT_SLIDES),
            "grabbed": False,
            "card": [card_x, card_y, card_w, card_h],
            "stride": stride,
            "slides": [
                dict(ATTRACT_SLIDES[i], index=i) for i in range(lo, hi + 1)
            ] if ATTRACT_SLIDES else [],
        }]

    elif SCENE == "picker":
        base["session"]["state"] = "experiments"
        base["buttons"] = [
            btn("exp.black_hole", "Black Hole", margin, margin, 150, 50, hovered=hover),
            btn("exp.slingshot", "Slingshot", margin + 160, margin, 150, 50),
            btn("exp.orbitals", "Orbitals", margin + 320, margin, 150, 50),
            btn("reset", "Reset", W - 130 - margin, H - 50 - margin, 130, 50),
        ]

    elif SCENE == "blackhole":
        base["session"]["state"] = "experiments"
        base["session"]["experiment"] = "black_hole"
        base["buttons"] = [
            btn("reset", "Reset", W - 130 - margin, H - 50 - margin, 130, 50)]
        base["objects"] = [{
            "type": "black_hole",
            "x": round(W / 2 + 140 * math.cos(t * 0.4), 1),
            "y": round(H / 2 + 80 * math.sin(t * 0.4), 1),
            "einstein_px": 80, "disk_inner_px": 120.0, "disk_outer_px": 320.0,
            "disk_tilt_rad": 1.2, "disk_brightness": 1.0,
            "rotation_speed": 0.8, "disk_t": round(t % 1000.0, 3),
            "grabbed": False,
        }]

    elif SCENE in ("slingshot", "slingaim"):
        base["session"]["state"] = "experiments"
        base["session"]["experiment"] = "slingshot"
        sb, lw = 46, 92
        plus_x = W - margin - sb
        base["buttons"] = [
            btn("speed.minus", "-", plus_x - lw - sb, margin, sb, sb),
            btn("speed.plus", "+", plus_x, margin, sb, sb),
            btn("reset", "Reset", W - 130 - margin, H - 50 - margin, 130, 50),
        ]
        base["speed"] = {"rect": [plus_x - lw, margin, lw, sb], "text": "1x"}
        ax, ay = W // 2, int(H * 0.82)
        aiming = True if SCENE == "slingaim" else (t % 6.0) < 3.0
        sling = {
            "type": "slingshot", "anchor": [ax, ay], "ball_r": 22,
            "aiming": aiming, "time_scale": 1.0,
            "pull": None, "readout": None, "arc": [], "projectiles": [],
        }
        if aiming:
            pull = [ax - 180, ay + 90]
            sling["pull"] = pull
            sling["readout"] = {"angle": 27.0, "v0": 12.4, "draw_n": 89.0,
                                "e_j": 90.0, "ke_j": 77.0}
            sling["arc"] = [
                [pull[0] + i * 28, pull[1] - int(120 * math.sin(i / 14 * math.pi))]
                for i in range(30)
            ]
        else:
            tt = (t % 6.0) - 3.0
            for pid in range(2):
                x = 200 + 380 * (tt + pid * 0.4)
                y = H * 0.75 - 320 * (tt + pid * 0.4) + 80 * (tt + pid * 0.4) ** 2
                sling["projectiles"].append({
                    "id": pid, "x": round(x, 1), "y": round(y, 1),
                    "resting": False, "sliding": False,
                    "f_w": [0.0, 9.81],
                    "f_d": [round(-3.2 - pid, 3), round(2.1, 3)],
                    "f_c": [0.0, 0.0],
                })
        base["objects"] = [sling]

    elif SCENE in ("orbitals", "orbaim"):
        base["session"]["state"] = "experiments"
        base["session"]["experiment"] = "orbitals"
        bw, bh, gap = 116, 46, 8
        x0 = y0 = margin
        y1 = y0 + bh + gap
        types = [("star", "Star"), ("planet", "Planet"),
                 ("moon", "Moon"), ("comet", "Comet")]
        for i, (k, lab) in enumerate(types):
            b = btn(f"orb.type.{k}", lab, x0 + i * (bw + gap), y0, bw, bh)
            b["selected"] = (k == "planet")
            base["buttons"].append(b)
        presets = [("solar", "Solar"), ("binary", "Binary"),
                   ("figure8", "Figure 8"), ("clear", "Clear")]
        for i, (pid, lab) in enumerate(presets):
            base["buttons"].append(
                btn(f"orb.preset.{pid}", lab, x0 + i * (bw + gap), y1, bw, bh))
        sb, lw = 46, 92
        plus_x = W - margin - sb
        base["buttons"] += [
            btn("speed.minus", "-", plus_x - lw - sb, margin, sb, sb),
            btn("speed.plus", "+", plus_x, margin, sb, sb),
            btn("reset", "Reset", W - 130 - margin, H - 50 - margin, 130, 50),
        ]
        base["speed"] = {"rect": [plus_x - lw, margin, lw, sb], "text": "1x"}
        cx, cy = W / 2, H / 2
        bodies = [{"id": 0, "x": round(cx, 1), "y": round(cy, 1), "r": 26,
                   "rgb": [255, 226, 158], "kind": "star", "m": 1200.0,
                   "flash": 0.0}]
        for i in range(3):
            ang = t * 0.6 + i * 2.1
            r = 120 + i * 72
            bodies.append({
                "id": i + 1,
                "x": round(cx + r * math.cos(ang), 1),
                "y": round(cy + r * math.sin(ang), 1),
                "r": 13, "rgb": [110, 170, 255], "kind": "planet", "m": 42.0,
                "flash": 0.0,
            })
        # A debris burst (recent fragmentation) with fading impact flashes.
        burst = 0.5 * (1 + math.sin(t * 0.8))
        for j in range(7):
            a = j / 7 * 2 * math.pi
            bodies.append({
                "id": 100 + j,
                "x": round(cx - 300 + math.cos(a) * (30 + burst * 90), 1),
                "y": round(cy + 150 + math.sin(a) * (30 + burst * 90), 1),
                "r": 5, "rgb": [200, 160, 120], "kind": "comet", "m": 4.0,
                "flash": round(max(0.0, 1 - burst * 1.4), 3),
            })
        aiming = SCENE == "orbaim"
        orb = {
            "type": "orbitals", "bodies": bodies, "count": len(bodies),
            "kind": "planet", "kind_r": 13, "kind_rgb": [110, 170, 255],
            "kind_m": 42.0, "time_scale": 1.0, "aiming": aiming,
            "spawn": None, "pull": None, "arc": [], "readout": None,
        }
        if aiming:
            sx, sy = cx - 240, cy - 40
            orb["spawn"] = [sx, sy]
            orb["pull"] = [sx - 120, sy + 100]
            orb["arc"] = [[sx + i * 26, sy - int(70 * math.sin(i / 16 * math.pi))]
                          for i in range(28)]
            orb["readout"] = {"v0": 286.0, "angle": 39.0, "kind": "planet",
                              "mass": 42.0}
        base["objects"] = [orb]

    elif SCENE == "waves":
        base["session"]["state"] = "experiments"
        base["session"]["experiment"] = "waves"
        bw, bh, gap = 116, 46, 8
        for i, (k, lab) in enumerate([("low", "Low"), ("mid", "Mid"),
                                      ("high", "High")]):
            b = btn(f"wave.freq.{k}", lab, margin + i * (bw + gap), margin,
                    bw, bh)
            b["selected"] = (k == "mid")
            base["buttons"].append(b)
        base["buttons"].append(
            btn("wave.clear", "Clear", margin + 3 * (bw + gap), margin,
                bw, bh))
        sb, lw = 46, 92
        plus_x = W - margin - sb
        base["buttons"] += [
            btn("speed.minus", "-", plus_x - lw - sb, margin, sb, sb),
            btn("speed.plus", "+", plus_x, margin, sb, sb),
            btn("reset", "Reset", W - 130 - margin, H - 50 - margin, 130, 50),
        ]
        base["speed"] = {"rect": [plus_x - lw, margin, lw, sb], "text": "1x"}
        # Two static mid sources (interference fringes between them) + one
        # slowly circling high source (Doppler wake).
        cx, cy = W / 2, H / 2
        # MOCK_WAVE_N=<n> scenes 1..5 sources (default 3) so the saturation
        # case (5 sources left running) can be reproduced headless.
        n_src = int(os.environ.get("MOCK_WAVE_N", "3"))
        all_src = [
            {"id": 0, "x": cx - 180, "y": cy + 40, "freq": 2.4, "amp": 1.0,
             "born": 0.0, "grabbed": False},
            {"id": 1, "x": cx + 180, "y": cy + 40, "freq": 2.4, "amp": 1.0,
             "born": 0.0, "grabbed": False},
            {"id": 2,
             "x": round(cx + 320 * math.cos(t * 0.5), 1),
             "y": round(cy - 180 + 60 * math.sin(t * 0.5), 1),
             "freq": 4.0, "amp": 1.0, "born": 2.0,
             "grabbed": int(t) % 4 == 0},
            {"id": 3, "x": cx - 400, "y": cy - 200, "freq": 1.2, "amp": 1.0,
             "born": 1.0, "grabbed": False},
            {"id": 4, "x": cx + 420, "y": cy + 220, "freq": 4.0, "amp": 1.0,
             "born": 3.0, "grabbed": False},
        ]
        sources = all_src[:max(1, min(5, n_src))]
        base["objects"] = [{
            "type": "waves", "t": round(t, 3), "c": 340.0,
            "time_scale": 1.0, "kind": "mid", "count": len(sources),
            "sources": sources,
        }]

    elif SCENE == "charges":
        base["session"]["state"] = "experiments"
        base["session"]["experiment"] = "charges"
        bw, bh, gap = 96, 46, 8
        kinds = [("neg2", "-2q"), ("neg1", "-q"), ("pos1", "+q"),
                 ("pos2", "+2q")]
        for i, (k, lab) in enumerate(kinds):
            b = btn(f"chg.type.{k}", lab, margin + i * (bw + gap), margin,
                    bw, bh)
            b["selected"] = (k == "pos1")
            base["buttons"].append(b)
        base["buttons"] += [
            btn("chg.preset.dipole", "Dipole", margin + 4 * (bw + gap),
                margin, bw, bh),
            btn("chg.clear", "Clear", margin + 5 * (bw + gap), margin, bw, bh),
            btn("reset", "Reset", W - 130 - margin, H - 50 - margin, 130, 50),
        ]
        # A dipole plus a roaming +2q, so field lines, the null point and the
        # 2q line-density convention are all visible at once.
        cx, cy = W / 2, H / 2
        charges = [
            {"id": 0, "x": cx - 240, "y": cy, "q": 1.0, "grabbed": False},
            {"id": 1, "x": cx + 240, "y": cy, "q": -1.0, "grabbed": False},
            {"id": 2,
             "x": round(cx + 60 * math.cos(t * 0.5), 1),
             "y": round(cy - 210 + 40 * math.sin(t * 0.5), 1),
             "q": 2.0, "grabbed": int(t) % 4 == 0},
        ]
        base["objects"] = [{
            "type": "charges", "k": 90000.0, "soften": 14.0,
            "equipot_step": 900.0, "lines_per_q": 12, "kind": "pos1",
            "count": len(charges), "charges": charges,
        }]

    elif SCENE == "magnets":
        base["session"]["state"] = "experiments"
        base["session"]["experiment"] = "magnets"
        bw, bh, gap = 96, 46, 8
        kinds = [("sn", "S-N"), ("ns", "N-S")]
        for i, (k, lab) in enumerate(kinds):
            b = btn(f"mag.type.{k}", lab, margin + i * (bw + gap), margin,
                    bw, bh)
            b["selected"] = (k == "sn")
            base["buttons"].append(b)
        base["buttons"] += [
            btn("mag.clear", "Clear", margin + 2 * (bw + gap), margin,
                bw, bh),
            btn("reset", "Reset", W - 130 - margin, H - 50 - margin, 130, 50),
        ]
        # One bar sweeping toward/away from the coil (its faked current is
        # the motion's derivative, so bulb + galvanometer breathe with it)
        # plus a parked flipped bar so both orientations render.
        coil_x, coil_y = W * 0.70, H * 0.52
        sweep = math.sin(t * 0.8)
        mags = [
            {"id": 0, "x": round(coil_x - 330 + 140 * sweep, 1),
             "y": round(coil_y, 1), "m": 1.0, "grabbed": int(t) % 4 == 0},
            {"id": 1, "x": W * 0.22, "y": H * 0.78, "m": -1.0,
             "grabbed": False},
        ]
        cur = round(0.8 * math.cos(t * 0.8), 3)
        base["objects"] = [{
            "type": "magnets", "half_len": 70.0, "half_h": 22.0,
            "edge_smooth": 12.0, "b_ref": 0.03, "needle_spacing": 38.0,
            "needle_len": 26.0, "kind": "sn", "count": len(mags),
            "magnets": mags,
            "coil": {"x": round(coil_x, 1), "y": round(coil_y, 1),
                     "r": 95.0, "loops": 3},
            "current": cur, "emf": round(cur * 8000.0, 1),
            # Real-unit mirror of the backend calibration: screen EMF *
            # MAG_EMF_TO_V (3.4e-8 V/unit), current over MAG_CIRCUIT_OHM.
            "emf_mv": round(cur * 8000.0 * 3.4e-8 * 1e3, 3),
            "current_ma": round(cur * 8000.0 * 3.4e-8 / 0.02 * 1e3, 1),
        }]

    elif SCENE == "spacetime":
        base["session"]["state"] = "experiments"
        base["session"]["experiment"] = "spacetime"
        bw, bh, gap = 96, 46, 8
        kinds = [("sun", "Sun"), ("neutron", "Neutron"), ("bh", "Hole"),
                 ("orbiter", "Orbiter")]
        for i, (k, lab) in enumerate(kinds):
            b = btn(f"st.type.{k}", lab, margin + i * (bw + gap), margin,
                    bw, bh)
            b["selected"] = (k == "sun")
            base["buttons"].append(b)
        base["buttons"] += [
            btn("st.view", "3D" if os.environ.get("HALL_MOCK_VIEW3D", "0") == "1" else "2D",
                margin + 4 * (bw + gap), margin, bw, bh),
            btn("st.top", "Top", margin + 5 * (bw + gap), margin, bw, bh),
            btn("st.preset.precess", "Precess", margin + 6 * (bw + gap),
                margin, bw, bh),
            btn("st.preset.binary", "Binary", margin + 7 * (bw + gap),
                margin, bw, bh),
            # Row 2 (the palette wraps at 8 per row, like the real manager)
            btn("st.preset.system", "System", margin, margin + bh + gap,
                bw, bh),
            btn("st.clear", "Clear", margin + (bw + gap), margin + bh + gap,
                bw, bh),
            btn("speed.minus", "-", W - margin - 46 - 92 - 46, margin, 46, 46),
            btn("speed.plus", "+", W - margin - 46, margin, 46, 46),
            btn("reset", "Reset", W - 130 - margin, H - 50 - margin, 130, 50),
        ]
        base["speed"] = {"rect": [W - margin - 46 - 92, margin, 92, 46],
                         "text": "1x"}
        cx, cy = W / 2, H / 2
        # Two wells (a star and a compact hole) so the summed sheet is visible,
        # plus an analytic PRECESSING ellipse — the trail the frontend
        # accumulates is what proves the renderer is drawing the walk.
        masses = [
            {"id": 0, "x": cx, "y": cy, "m": 1.0, "rs": 2.5,
             "rgb": [255, 226, 158], "compact": False, "kind": "sun", "r_body": 50.0,
             "flash": 0.0, "grabbed": False, "spin": 0.1,
             "phase": round(t * 0.8 % 6.283, 3),
             "r_horizon": 2.49, "r_ergo": 2.5},
            # a* = 0.9: horizon shrinks to 0.63*rs while the ergosphere stays
            # at rs -> a visible gap, and a strong 1/r^3 twist nearby.
            {"id": 1, "x": round(cx + 330, 1), "y": round(cy - 90, 1),
             "m": 4.0, "rs": 10.0, "rgb": [18, 16, 26], "compact": True,
             "kind": "bh", "r_body": 10.0, "flash": 0.0, "grabbed": False, "spin": 0.9,
             "phase": round(t * 2.4 % 6.283, 3),
             "r_horizon": 7.18, "r_ergo": 10.0},
        ]
        a_axis, ecc = 200.0, 0.45
        theta = t * 0.9
        apsis = t * 0.25            # apsidal precession
        rr = a_axis * (1 - ecc * ecc) / (1 + ecc * math.cos(theta))
        orbiters = [{
            "id": 0,
            "x": round(cx + rr * math.cos(theta + apsis), 1),
            "y": round(cy + rr * math.sin(theta + apsis), 1),
        }]
        base["objects"] = [{
            "type": "spacetime",
            # Slow yaw sweep so a screenshot at any t shows the 3D structure.
            "yaw": round(t * 0.15, 4) if MOCK_YAW else 0.0,
            "pitch": round(math.radians(34.0), 4),
            "zoom": 0.75,
            "focal": 1700.0,
            "rotating": int(t) % 8 < 2,
            "reach": 460.0,
            "depth_gain": 1.0,
            "grid": [30, 18, 72, 2.3],
            "view_3d": os.environ.get("HALL_MOCK_VIEW3D", "0") == "1",
            "lattice": [12, 8, 5, 44, 1.55, 300.0],
            "lattice_verticals": True,
            "lattice_gain": 7.0,
            "vert_stride": 2,
            "c": round((2 * 4.2e6 / 2.5) ** 0.5, 4),
            "g": 4.2e6,
            "lt_gain": 1.0,
            "lt_max": 1.1,
            "dim": 0.45,
            "dim_rgb": [6, 8, 18],
            "kind": "sun",
            "time_scale": 1.0,
            "count": len(masses),
            "masses": masses,
            "orbiters": orbiters,
            "orbiter_rgb": [140, 235, 255],
            "trail_len": 360,
            # A fake binary's quadrupole, so the ripple can be seen headless.
            "sim_t": round(t, 4),
            "quad": [round(4e4*math.cos(2*t*1.6), 3),
                     round(-4e4*math.cos(2*t*1.6), 3),
                     round(4e4*math.sin(2*t*1.6), 3)],
            "com": [cx, cy],
            "gw_gain": 4.0e4,
            "gw_max": 60.0,
            "gw_hist_s": 2.0,
            "ghost": None,
        }]

    elif SCENE == "schrodinger":
        # Cycles the four phases every 24 s: cat dragged in (0-6), trigger
        # idle + recoil/particle flight (6-12), superposition ghosts (12-18),
        # collapse (18-24, outcome alternates per cycle). Mirrors the 1935
        # apparatus contract: alpha gun + FIRE trigger + Geiger tube.
        base["session"]["state"] = "experiments"
        base["session"]["experiment"] = "schrodinger"
        base["buttons"] = [
            btn("reset", "Reset", W - 130 - margin, H - 50 - margin, 130, 50)]
        bw, bh = 0.24 * W, 0.36 * H
        bx, by = 0.62 * W - bw / 2, 0.55 * H - bh / 2
        geiger = [round(bx, 1), round(by + bh * 0.45, 1)]
        gun_w = 0.13 * W
        gun = [round(0.35 * W, 1), geiger[1]]
        trigger = [round(gun[0] - gun_w * 0.55, 1),
                   round(gun[1] + gun_w * 0.62, 1)]
        cyc = t % 24.0
        obj = {
            "type": "schrodinger", "phase": "place",
            "cat": [round(0.28 * W, 1), round(0.62 * H, 1)],
            "cat_r": round(0.055 * H, 1), "cat_grabbed": False,
            "box": [round(bx, 1), round(by, 1), round(bw, 1), round(bh, 1)],
            "gun": gun, "gun_w": round(gun_w, 1),
            "trigger": trigger, "trigger_r": 70,
            "geiger": geiger, "geiger_r": 46,
            "recoil": 0.0, "particle": None,
            "outcome": None, "flash": 0.0, "tally": [3, 2], "caption": "",
        }
        if cyc < 6.0:
            f = min(1.0, cyc / 5.0)
            obj["cat"] = [round(0.28 * W + (bx + bw / 2 - 0.28 * W) * f, 1),
                          round(0.62 * H + (by + bh / 2 - 0.62 * H) * f, 1)]
            obj["cat_grabbed"] = f < 0.95
            obj["caption"] = "Pinch to grab the cat, drop it inside the box"
        elif cyc < 12.0:
            obj["phase"] = "armed"
            obj["caption"] = ("Now pinch the FIRE button: shoot the alpha"
                             " particle at the box")
            if cyc >= 9.0:
                f = (cyc - 9.0) / 3.0
                obj["recoil"] = round(max(0.0, 1.0 - f * 4.0), 3)
                obj["particle"] = [
                    round(gun[0] + (geiger[0] - gun[0]) * f, 1),
                    round(gun[1] + (geiger[1] - gun[1]) * f, 1)]
        elif cyc < 18.0:
            obj["phase"] = "superposed"
            obj["caption"] = ("Closed box: the cat is alive AND dead at the"
                              " same time. Pinch it to look")
        else:
            alive = int(t / 24.0) % 2 == 0
            obj["phase"] = "revealed"
            obj["outcome"] = "alive" if alive else "dead"
            obj["flash"] = round(max(0.0, 1.0 - (cyc - 18.0)), 3)
            obj["caption"] = (
                "It's ALIVE - the poison never broke."
                " Pinch the box to play again" if alive
                else "It's DEAD - the hammer smashed the poison."
                " Pinch the box to play again")
        base["objects"] = [obj]

    return base


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path in ("/stream.mjpg", "/stream"):
            self.send_response(200)
            self.send_header("Content-Type",
                             "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            try:
                while True:
                    self.wfile.write(
                        b"--frame\r\nContent-Type: image/jpeg\r\n"
                        b"Content-Length: " + str(len(JPG)).encode()
                        + b"\r\n\r\n" + JPG + b"\r\n")
                    time.sleep(1 / 15)
            except (BrokenPipeError, ConnectionResetError):
                pass
        elif self.path == "/state":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            # match the real backend (output.py): allow cross-origin reads so
            # the Slidev deck's gesture overlay can subscribe from another port.
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            seq = 0
            try:
                while True:
                    t = time.monotonic() - START
                    seq += 1
                    state = {
                        "seq": seq, "t": round(t, 3),
                        "frame": {"w": W, "h": H},
                        "hands": [fake_hand(t)], "pose": None,
                        "debug": {"render_fps": 30.0, "hand_fps": 30.0,
                                  "age_ms": 15.0, "backend": "mock",
                                  "gesture": GESTURE,
                                  "close_ratio": 0.45, "release_ratio": 0.9,
                                  "fist_close_ratio": 1.05,
                                  "fist_release_ratio": 1.30,
                                  "presence": {"present": True,
                                               "motion": 0.18,
                                               "blob": 0.16, "span": 0.62,
                                               "hand": 0.22,
                                               "source": "hand"}},
                    }
                    state.update(scene_state(t))
                    payload = json.dumps(state, separators=(",", ":"))
                    self.wfile.write(b"data: " + payload.encode() + b"\n\n")
                    time.sleep(1 / 30)
            except (BrokenPipeError, ConnectionResetError):
                pass
        elif self.path.startswith("/attract/"):
            full = os.path.join(ATTRACT_DIR,
                                os.path.basename(unquote(self.path)))
            if not os.path.isfile(full):
                self.send_error(404)
                return
            with open(full, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/healthz":
            body = b"ok\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)


if __name__ == "__main__":
    print(f"mock backend on http://127.0.0.1:{PORT}  scene={SCENE}")
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    server.serve_forever()
