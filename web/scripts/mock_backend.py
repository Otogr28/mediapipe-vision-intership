"""Mock HalLMediaPipe backend for frontend development without a camera.

Serves the same contract as `src/output.WebSink` — `/stream.mjpg` (a
synthetic test-card frame), `/state` (SSE, animated scenes) and `/healthz`
— so every UI state can be exercised deterministically, no gestures needed.

Run from the repo root (needs the repo venv for cv2/numpy):

    uv run python web/scripts/mock_backend.py [scene]

Scenes: menu (default), sphere, sixseven, slingshot, blackhole, picker,
orbitals, orbaim, vtuber.
Then point the vite dev server at it:  npm run dev  (same port 8092).
"""

import json
import math
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

W, H = 1280, 720
PORT = 8092
SCENE = sys.argv[1] if len(sys.argv) > 1 else "menu"

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


def vtuber_pose(t):
    """Synthetic 33-landmark pose (mirrored-feed labelling, like the real
    backend): the person's RIGHT arm (idx 12/14/16, on the image RIGHT) is
    raised UP, their LEFT arm (11/13/15, image LEFT) is held out HORIZONTAL.
    Asymmetric on purpose so the mirror mapping is obvious — the avatar's
    image-right arm should go up, its image-left arm should point left."""
    wob = 0.03 * math.sin(t * 1.5)
    lm = [[0.5, 0.5, 0.4] for _ in range(33)]
    lm[0] = [0.5, 0.30, 0.99]                       # nose
    # image-LEFT side (person's left arm) — held out horizontally left
    lm[11] = [0.40, 0.42, 0.99]                     # L shoulder
    lm[13] = [0.29, 0.44, 0.99]                     # L elbow
    lm[15] = [0.18, 0.46 + wob, 0.99]               # L wrist
    # image-RIGHT side (person's right arm) — raised straight up
    lm[12] = [0.60, 0.42, 0.99]                     # R shoulder
    lm[14] = [0.64, 0.30, 0.99]                     # R elbow
    lm[16] = [0.68, 0.16 + wob, 0.99]               # R wrist
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

    elif SCENE == "vtuber":
        base["session"]["state"] = "interactables"
        base["buttons"] = [
            btn("spawn.sphere", "Sphere", margin, margin, 120, 50),
            btn("spawn.vtuber", "Vtuber", margin + 130, margin, 150, 50, pressed=True),
            btn("reset", "Reset", W - 130 - margin, H - 50 - margin, 130, 50),
        ]
        # Two hands so both paws + arms render; landmarks null -> the puppet
        # anchors to the pinch cursor.
        base["hands"] = [
            {"id": "Left", "cursor": [round(W * 0.36 + 60 * math.cos(t), 1),
                                      round(H * 0.62 + 50 * math.sin(t * 1.3), 1)],
             "press_cursor": [W * 0.36, H * 0.62], "state": "open",
             "progress": round(0.5 * (1 - math.cos(t * 1.7)), 3),
             "ratio": 0.7, "pinching": False, "held": False,
             "seen_ms": 0.0, "landmarks": None},
            {"id": "Right", "cursor": [round(W * 0.64 + 60 * math.cos(t + 1), 1),
                                       round(H * 0.6 + 50 * math.sin(t * 1.1), 1)],
             "press_cursor": [W * 0.64, H * 0.6], "state": "open",
             "progress": round(0.5 * (1 - math.cos(t * 2.1)), 3),
             "ratio": 0.7, "pinching": False, "held": False,
             "seen_ms": 0.0, "landmarks": None},
        ]
        base["pose"] = vtuber_pose(t)
        base["pose_world"] = vtuber_world(t)
        base["objects"] = [{
            "type": "vtuber", "t": round(t % 1000.0, 3),
            "mouth": round(0.5 * (1 - math.cos(t * 1.8)), 3),
        }]

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
