"""Mock HalLMediaPipe backend for frontend development without a camera.

Serves the same contract as `src/output.WebSink` — `/stream.mjpg` (a
synthetic test-card frame), `/state` (SSE, animated scenes) and `/healthz`
— so every UI state can be exercised deterministically, no gestures needed.

Run from the repo root (needs the repo venv for cv2/numpy):

    uv run python web/scripts/mock_backend.py [scene]

Scenes: menu (default), sphere, sixseven, slingshot, blackhole, picker,
orbitals, orbaim, waves, charges, spacetime, vtuber, schrodinger.
Then point the vite dev server at it:  npm run dev  (same port 8092).
"""

import json
import math
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

W, H = 1280, 720
PORT = 8092
SCENE = sys.argv[1] if len(sys.argv) > 1 else "menu"
# spacetime: set HALL_MOCK_YAW=0 to freeze the camera at the default view.
MOCK_YAW = os.environ.get("HALL_MOCK_YAW", "1") == "1"

START = time.monotonic()


def test_card():
    """Synthetic background: gradient + grid + circles — enough structure
    to judge overlays and (crucially) the black-hole lensing distortion."""
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


def vtuber_center(t):
    """Moving body centre (norm image) + half shoulder-width, so the avatar's
    root-follow (translation) and distance-scale can be verified headless."""
    cx = 0.5 + 0.22 * math.sin(t * 0.5)     # slide left/right across the frame
    cy = 0.42 + 0.05 * math.sin(t * 0.37)   # drift up/down
    hw = 0.10 + 0.03 * math.sin(t * 0.6)    # shoulder half-width -> avatar scale
    return cx, cy, hw


def vtuber_pose(t):
    """Synthetic 33-landmark 2D pose (mirrored-feed labelling). The image-RIGHT
    arm (12/14/16) is raised, the image-LEFT arm (11/13/15) is horizontal —
    asymmetric so the mirror is obvious. The whole body slides + breathes
    (vtuber_center) to exercise the avatar's screen-position follow + scale."""
    wob = 0.03 * math.sin(t * 1.5)
    cx, cy, hw = vtuber_center(t)
    lm = [[cx, cy + 0.10, 0.5] for _ in range(33)]
    lm[0] = [cx, cy - 0.12, 0.99]                      # nose
    # image-LEFT arm — held out horizontally to the left
    lm[11] = [cx - hw, cy, 0.99]                        # L shoulder
    lm[13] = [cx - hw - 0.11, cy + 0.02, 0.99]         # L elbow
    lm[15] = [cx - hw - 0.22, cy + 0.04 + wob, 0.99]   # L wrist
    lm[19] = [cx - hw - 0.25, cy + 0.04 + wob, 0.99]   # L index
    # image-RIGHT arm — raised straight up
    lm[12] = [cx + hw, cy, 0.99]                        # R shoulder
    lm[14] = [cx + hw + 0.04, cy - 0.12, 0.99]         # R elbow
    lm[16] = [cx + hw + 0.08, cy - 0.26 + wob, 0.99]   # R wrist
    lm[20] = [cx + hw + 0.10, cy - 0.30 + wob, 0.99]   # R index
    # hips (spine gating)
    lm[23] = [cx - 0.06, cy + 0.34, 0.9]               # L hip
    lm[24] = [cx + 0.06, cy + 0.34, 0.9]               # R hip
    return [[round(a, 4), round(b, 4), round(c, 2)] for a, b, c in lm]


def vtuber_world(t):
    """Synthetic metric 3D skeleton (`pose_world_landmarks`) matching the 2D
    `vtuber_pose`: meters, origin at hips midpoint, +x image-right, +y DOWN,
    +z away from camera. The image-right arm (idx 12/14/16) is raised and, on
    a slow cycle, REACHES toward the camera (negative z) so the depth mapping
    is visible; the image-left arm (11/13/15) is held out horizontally."""
    reach = 0.5 * (1.0 - math.cos(t * 1.3))   # 0..1, raised arm reaches forward
    zf = -0.38 * reach                        # toward camera (=> +z in three.js)
    zl = 0.12 * math.sin(t * 1.5)             # left arm slow depth wobble
    lm = [[0.0, 0.0, 0.0] for _ in range(33)]
    lm[0] = [0.0, -0.72, -0.05]                       # nose
    # image-LEFT arm (person's left) — held out horizontal to the left
    lm[11] = [-0.18, -0.50, 0.0]                      # L shoulder
    lm[13] = [-0.42, -0.50, zl]                       # L elbow
    lm[15] = [-0.64, -0.50, zl]                       # L wrist
    lm[19] = [-0.70, -0.50, zl]                       # L index
    lm[17] = [-0.69, -0.47, zl]                       # L pinky
    # image-RIGHT arm (person's right) — raised up, reaching toward camera
    lm[12] = [0.18, -0.50, 0.0]                       # R shoulder
    lm[14] = [0.30, -0.72, zf]                        # R elbow
    lm[16] = [0.36, -0.95, zf]                        # R wrist
    lm[20] = [0.38, -1.05, zf]                        # R index
    lm[18] = [0.34, -1.03, zf]                        # R pinky
    # hips + legs (mostly off-frame in the avatar shot; here just for the spine)
    lm[23] = [-0.12, 0.0, 0.0]                        # L hip
    lm[24] = [0.12, 0.0, 0.0]                         # R hip
    lm[25] = [-0.13, 0.45, 0.0]                       # L knee
    lm[26] = [0.13, 0.45, 0.0]                        # R knee
    lm[27] = [-0.13, 0.90, 0.0]                       # L ankle
    lm[28] = [0.13, 0.90, 0.0]                        # R ankle
    return [[round(a, 3), round(b, 3), round(c, 3)] for a, b, c in lm]


def _finger_points(mcp, segs, curl):
    """MCP + 3 joint points for one finger, bending toward the palm (-z) as
    `curl` (0..1) rises; more bend at the distal joints."""
    pts = [list(mcp)]
    pos = list(mcp)
    ang = 0.0
    for i, seg_len in enumerate(segs):
        ang += curl * (0.5 if i == 0 else 1.0)
        pos = [pos[0], pos[1] + seg_len * math.cos(ang),
               pos[2] - seg_len * math.sin(ang)]
        pts.append(list(pos))
    return pts


def fake_hand_world(t, side):
    """Synthetic 21-pt metric hand skeleton (wrist origin). Fingers curl on a
    slow cycle and the whole palm ROLLS about the finger axis so palm-facing is
    visible. The absolute orientation is rough (exact convention is confirmed on
    the real camera) — the point is that the palm turns and the fingers bend."""
    curl = 0.5 * (1.0 - math.cos(t * 0.9))     # 0..1 open -> fist
    roll = 0.9 * math.sin(t * 0.6)             # palm swivels toward/away
    sx = 1.0 if side == "Right" else -1.0      # mirror the thumb for the left hand
    w3 = [[0.0, 0.0, 0.0] for _ in range(21)]
    bases = {
        "thumb":  ([0.035 * sx, 0.015, 0.010], [0.035, 0.030, 0.025]),
        "index":  ([0.022 * sx, 0.060, 0.0], [0.040, 0.025, 0.020]),
        "middle": ([0.005 * sx, 0.065, 0.0], [0.045, 0.030, 0.022]),
        "ring":   ([-0.015 * sx, 0.060, 0.0], [0.040, 0.028, 0.020]),
        "little": ([-0.033 * sx, 0.052, 0.0], [0.030, 0.022, 0.016]),
    }
    slots = {"thumb": (1, 2, 3, 4), "index": (5, 6, 7, 8),
             "middle": (9, 10, 11, 12), "ring": (13, 14, 15, 16),
             "little": (17, 18, 19, 20)}
    for name, (mcp, segs) in bases.items():
        pts = _finger_points(mcp, segs, curl * (0.6 if name == "thumb" else 1.0))
        for slot, p in zip(slots[name], pts):
            w3[slot] = p
    c, s = math.cos(roll), math.sin(roll)      # roll about the finger (y) axis
    return [[round(x * c + z * s, 4), round(y, 4), round(-x * s + z * c, 4)]
            for x, y, z in w3]


def fake_hand_2d(world, wx, wy, scale=0.7):
    """21 norm-image [x,y] points: the 3D hand's (x,y) projected around the wrist
    screen pos, so the skeleton view shows a real hand shape. Only [0] (wrist) is
    read for hand->avatar side matching; the rest feed the debug overlay."""
    w0 = world[0]
    return [[round(wx + (p[0] - w0[0]) * scale, 4),
             round(wy + (p[1] - w0[1]) * scale, 4)] for p in world]


def scene_state(t):
    margin = int(H * 0.12)
    hover = int(t) % 2 == 0
    base = {
        "session": {"state": "menu", "experiment": None,
                    "hint": {"visible": False}},
        "buttons": [], "speed": None, "objects": [],
    }

    if SCENE == "menu":
        bw, bh, gap = 260, 70, 16
        sx = (W - 2 * bw - gap) // 2
        base["buttons"] = [
            btn("menu.interactables", "Interactable Figures", sx, margin, bw, bh, hovered=hover),
            btn("menu.experiments", "Experiments", sx + bw + gap, margin, bw, bh),
        ]
        base["session"]["hint"] = {"visible": True}

    elif SCENE in ("sphere", "sixseven"):
        base["session"]["state"] = "interactables"
        base["buttons"] = [
            btn("spawn.sphere", "Sphere", margin, margin, 120, 50),
            btn("spawn.sixseven", "6 7 Counter", margin + 130, margin, 170, 50),
            btn("reset", "Reset", W - 130 - margin, H - 50 - margin, 130, 50),
        ]
        if SCENE == "sphere":
            base["objects"] = [{
                "type": "sphere", "id": 0,
                "x": round(W / 2 + 320 * math.sin(t * 1.7), 1),
                "y": round(H / 2 + 180 * math.sin(t * 2.3), 1),
                "r": 40, "grabbed": int(t) % 4 == 0,
            }]
        else:
            base["objects"] = [{
                "type": "sixseven", "count": int(t) % 30,
                "flash": max(0.0, 1.0 - (t % 1.0) * 2),
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
            btn("st.clear", "Clear", margin + 7 * (bw + gap), margin, bw, bh),
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
            "zoom": 1.0,
            "focal": 1700.0,
            "rotating": int(t) % 8 < 2,
            "reach": 460.0,
            "depth_gain": 1.0,
            "grid": [30, 18, 72, 1.7],
            "view_3d": os.environ.get("HALL_MOCK_VIEW3D", "0") == "1",
            "lattice": [12, 8, 5, 44, 1.15, 300.0],
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
        # Cycles the four phases every 24 s: cat dragged in (0-6), aim +
        # particle flight (6-12), superposition ghosts (12-18), collapse
        # (18-24, outcome alternates per cycle).
        base["session"]["state"] = "experiments"
        base["session"]["experiment"] = "schrodinger"
        base["buttons"] = [
            btn("reset", "Reset", W - 130 - margin, H - 50 - margin, 130, 50)]
        bw, bh = 0.24 * W, 0.36 * H
        bx, by = 0.62 * W - bw / 2, 0.55 * H - bh / 2
        emitter = [round(0.35 * W, 1), round(0.53 * H, 1)]
        detector = [round(bx, 1), round(by + bh * 0.45, 1)]
        cyc = t % 24.0
        obj = {
            "type": "schrodinger", "phase": "place",
            "cat": [round(0.28 * W, 1), round(0.62 * H, 1)],
            "cat_r": round(0.055 * H, 1), "cat_grabbed": False,
            "box": [round(bx, 1), round(by, 1), round(bw, 1), round(bh, 1)],
            "emitter": emitter, "detector": detector, "detector_r": 46,
            "aiming": False, "pull": None, "particle": None,
            "outcome": None, "flash": 0.0, "tally": [3, 2], "caption": "",
        }
        if cyc < 6.0:
            f = min(1.0, cyc / 5.0)
            obj["cat"] = [round(0.28 * W + (bx + bw / 2 - 0.28 * W) * f, 1),
                          round(0.62 * H + (by + bh / 2 - 0.62 * H) * f, 1)]
            obj["cat_grabbed"] = f < 0.95
            obj["caption"] = "Pinch the cat, drop it in the box"
        elif cyc < 12.0:
            obj["phase"] = "armed"
            obj["caption"] = "Pinch the emitter, pull back, release to fire"
            if cyc < 9.0:
                ang = 0.5 * math.sin(t * 1.3)
                obj["aiming"] = True
                obj["pull"] = [round(emitter[0] - 150 * math.cos(ang), 1),
                               round(emitter[1] + 150 * math.sin(ang) + 60, 1)]
            else:
                f = (cyc - 9.0) / 3.0
                obj["particle"] = [
                    round(emitter[0] + (detector[0] - emitter[0]) * f, 1),
                    round(emitter[1] + (detector[1] - emitter[1]) * f, 1)]
        elif cyc < 18.0:
            obj["phase"] = "superposed"
            obj["caption"] = ("Nobody looked: it decayed AND didn't."
                              " Pinch the box to open it")
        else:
            alive = int(t / 24.0) % 2 == 0
            obj["phase"] = "revealed"
            obj["outcome"] = "alive" if alive else "dead"
            obj["flash"] = round(max(0.0, 1.0 - (cyc - 18.0)), 3)
            obj["caption"] = (
                "Measured: ALIVE. Pinch the box to run it again" if alive
                else "Measured: DEAD. Pinch the box to run it again")
        base["objects"] = [obj]

    elif SCENE == "vtuber":
        base["session"]["state"] = "interactables"
        base["buttons"] = [
            btn("spawn.sphere", "Sphere", margin, margin, 120, 50),
            btn("spawn.vtuber", "Rigged Model", margin + 130, margin, 150, 50, pressed=True),
            btn("reset", "Reset", W - 130 - margin, H - 50 - margin, 130, 50),
        ]
        # Two hands placed at each arm's WRIST so the avatar's image-x hand
        # matcher pairs hand<->arm on the same screen side; each carries a full
        # 21-pt 3D `world` skeleton (palm roll + finger curl) + handedness.
        cx, cy, hw = vtuber_center(t)
        wl_x, wl_y = cx - hw - 0.22, cy + 0.04      # image-LEFT wrist (horizontal arm)
        wr_x, wr_y = cx + hw + 0.08, cy - 0.26      # image-RIGHT wrist (raised arm)
        world_r = fake_hand_world(t, "Right")
        world_l = fake_hand_world(t, "Left")
        base["hands"] = [
            {"id": "handR", "cursor": [round(wr_x * W, 1), round(wr_y * H, 1)],
             "press_cursor": [round(wr_x * W, 1), round(wr_y * H, 1)], "state": "open",
             "progress": round(0.5 * (1 - math.cos(t * 2.1)), 3),
             "ratio": 0.7, "pinching": False, "held": False, "seen_ms": 0.0,
             "landmarks": fake_hand_2d(world_r, wr_x, wr_y),
             "world": world_r, "handedness": "Right"},
            {"id": "handL", "cursor": [round(wl_x * W, 1), round(wl_y * H, 1)],
             "press_cursor": [round(wl_x * W, 1), round(wl_y * H, 1)], "state": "open",
             "progress": round(0.5 * (1 - math.cos(t * 1.7)), 3),
             "ratio": 0.7, "pinching": False, "held": False, "seen_ms": 0.0,
             "landmarks": fake_hand_2d(world_l, wl_x, wl_y),
             "world": world_l, "handedness": "Left"},
        ]
        base["pose"] = vtuber_pose(t)
        base["pose_world"] = vtuber_world(t)
        base["objects"] = [{
            "type": "vtuber", "t": round(t % 1000.0, 3),
            "mouth": round(0.5 * (1 - math.cos(t * 1.8)), 3),
        }]
        # "Points" pinch toggle (alternates every 4 s so a screenshot catches
        # both the avatar and the skeleton view driven by the backend flag).
        # MOCK_NO_POINTS=1 pins it off so the avatar is always shown (handy when
        # verifying a specific avatar without waiting out the toggle).
        show_points = int(t / 4) % 2 == 1 and os.environ.get("MOCK_NO_POINTS") != "1"
        base["session"]["show_points"] = show_points
        # Cycle the avatar every 5 s so the state-driven switcher is testable
        # (the real backend sets this from the "Avatar" pinch button).
        base["session"]["avatar_index"] = int(t / 5) % 6
        pbtn = btn("points", "Points", margin, H - 50 - margin, 150, 50)
        pbtn["selected"] = show_points
        base["buttons"].append(pbtn)

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
                                  "close_ratio": 0.45, "release_ratio": 0.9},
                    }
                    state.update(scene_state(t))
                    payload = json.dumps(state, separators=(",", ":"))
                    self.wfile.write(b"data: " + payload.encode() + b"\n\n")
                    time.sleep(1 / 30)
            except (BrokenPipeError, ConnectionResetError):
                pass
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
