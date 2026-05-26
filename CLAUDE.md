# HalLMediaPipe — Claude Code Guidelines

## Project structure

```
src/
  main.py               — entry point: camera loop only, no UI logic
  config.py             — global constants (camera index, thresholds, …)
  detection/
    detectors.py        — MediaPipe pose/hand detector setup + shared results
  rendering/
    drawing.py          — landmark/connection drawing helpers
  ui/
    manager.py          — all UI state, buttons, and interactable objects
    button.py           — Button widget (hand-pinch interaction)
    interactables.py    — physics objects (BouncingSphere, …)
```

## Modularity preference

Keep `main.py` thin: camera capture, detector calls, and drawing landmarks only.
All UI logic (state machine, button layout, scene objects) belongs in `ui/manager.py` or dedicated modules — never inline in `main.py`.

When adding a new mode or feature:
- New UI state → add it to `UIManager` in `ui/manager.py`
- New interactable object type → add it to `ui/interactables.py`
- New button widget behavior → add it to `ui/button.py`

## Language

All code, comments, and commit messages are written in English.
