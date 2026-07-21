# /// script
# requires-python = ">=3.10"
# dependencies = ["segno>=1.6"]
# ///
"""Generate the per-experiment QR codes for the kiosk plates.

Each RUNNING experiment shows a white plate bottom-left (see
UIManager._draw_qr_placeholder / scene.ts drawQrPlaceholder). This script
renders one QR PNG per experiment key pointing at its GitHub Pages info
page, into web/src/assets/qr/ — where BOTH renderers pick them up (Vite
import on the web side, cv2.imread on the Python side). Re-run after
changing BASE_URL or adding an experiment:

    uv run web/scripts/gen_qr.py

PEP 723 inline deps: uv runs this in its own throwaway env — segno never
touches the app's pyproject/uv.lock.

Design notes:
- error correction M, byte mode (the URL path is lowercase; alnum mode
  can't encode it) → version 5, 37 modules.
- border=2 modules in the PNG; the white plate around the code supplies
  the rest of the ISO quiet zone (>= 4 modules total at plate scale).
- dark color is the site's Gordon navy — near-black, scans fine, and ties
  the plate to the site it links to.
"""

import os

import segno

# Keep in sync with the `session.experiment` union in src/ui/manager.py
# to_state() / web/src/state/types.ts, and with the pages under docs/.
EXPERIMENTS = [
    "black_hole",
    "slingshot",
    "orbitals",
    "waves",
    "charges",
    "spacetime",
    "schrodinger",
]

BASE_URL = "https://otogr28.github.io/mediapipe-vision-intership"
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "src", "assets", "qr")

NAVY = "#0A1724"   # Gordon dark navy (docs/style.css --navy)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for key in EXPERIMENTS:
        url = f"{BASE_URL}/experiments/{key}.html"
        qr = segno.make(url, error="m")
        path = os.path.join(OUT_DIR, f"{key}.png")
        # scale 12 → ~490 px: crisp when downscaled to the ~115 px plate.
        qr.save(path, scale=12, border=2, dark=NAVY, light="#ffffff")
        print(f"{key:12s} v{qr.version}  {url}")


if __name__ == "__main__":
    main()
