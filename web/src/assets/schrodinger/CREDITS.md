# Schrödinger scene sprite credits

All sprites are extracted (cropped, background-keyed, resized) from CC0 /
public-domain sources — no attribution legally required, credited anyway:

- `cat_alive.png`, `device.png`, `flask.png`, `flask_tipped.png` (derived) —
  from "Schroedingers cat box.svg" by **Christian Schirm** (Wikimedia Commons,
  CC0 1.0): <https://commons.wikimedia.org/wiki/File:Schroedingers_cat_box.svg>
- `cat_dead.png` — from "Schroedingers cat experiment.svg" by **Christian
  Schirm** (Wikimedia Commons, CC0 1.0):
  <https://commons.wikimedia.org/wiki/File:Schroedingers_cat_experiment.svg>
- `gun.png` — "Ray gun" (FreeSVG, public domain / CC0, flipped horizontally):
  <https://freesvg.org/ray-gun>

These files are consumed by BOTH renderers: the web frontend imports them via
Vite, and the cv2 fallback (`src/ui/interactables.py`) reads the same PNGs from
this directory relative to the repo root. `.gitignore` re-includes this folder
past the global `*.png` rule — keep it that way or the exhibit loses the art.
