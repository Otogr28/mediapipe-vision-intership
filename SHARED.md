# SHARED.md — Agent Coordination File

This file is the coordination space between AI agents (Claude, Codex, or others) working on this project. Use it to leave useful context for the next agent, including:

- current project status
- important decisions made
- files changed
- commands run
- bugs found
- assumptions
- unfinished tasks
- warnings or things to avoid
- next recommended steps

## How to use

1. **Before starting any new task**, read this file in full and treat it as project context.
2. **After completing meaningful work**, append a short update at the bottom of the file using the format below.
3. **Do not overwrite another agent's notes.** Only remove context that is clearly outdated and is being replaced with better information.
4. Keep updates concise — link to files and commits instead of pasting long content.

## Update format

```
## Update - YYYY-MM-DD HH:MM - [Agent Name]

### What I did
- ...

### Files changed
- ...

### Important context for the other agent
- ...

### Next steps / unfinished work
- ...
```

## Project overview

This repository supports a 10-week Physics Department internship. Main focus areas:

- Learning **Autodesk Inventor 2027** (not AutoCAD).
- Learning **safe 3D printing workflows** (regular and resin). For resin work, never suggest unsafe shortcuts — always respect PPE, ventilation, resin handling, curing, cleaning, and disposal procedures.
- Building a **secure and maintainable Physics Department website** with:
  - Student Research Expo
  - Physics Hall Exhibits / Curiosity Gallery with QR-linked pages
  - A real admin system with secure authentication practices (no hardcoded passwords, no fake auth).

Coding values: clean, beginner-friendly, secure, and maintainable.

---

## Update - 2026-05-20 14:41 - Claude (Opus 4.7)

### What I did
- Created this `SHARED.md` to start the AI-agent coordination workflow.
- Appended a "Shared Agent Context Rule" section to `AGENTS.md` pointing here.

### Files changed
- `SHARED.md` (new)
- `AGENTS.md` (appended rule section)

### Important context for the other agent
- Repo currently holds a near-empty `uv`-managed Python project: `main.py` is a hello-world stub, dependencies are pinned in `uv.lock`, and there is no test suite yet.
- The internship has three parallel tracks (Inventor 2027, 3D printing, Physics Dept website). None of them have code in this repo yet — this repo so far only contains the MediaPipe/Python scaffold.
- Safety reminder for the human collaborator: **resin printing workflows must always include PPE, ventilation, proper curing, cleaning, and disposal** — do not suggest shortcuts.
- Security reminder for the website work: **no hardcoded passwords or fake authentication**. Use a real auth approach when that work begins.

### Next steps / unfinished work
- Clarify with the user how the MediaPipe Python work relates to the three internship tracks (is it for a Curiosity Gallery exhibit? a 3D-printing helper? something else?).
- Decide where the Physics Department website will live (this repo vs. a separate repo) before scaffolding it.
- Add a `tests/` directory + first `pytest` smoke test once real code lands in `main.py`.

## Update - 2026-05-20 14:42 - Codex

### What I did
- Read `SHARED.md` before making changes.
- Verified that `SHARED.md` already exists and contains the required AI-agent coordination instructions.
- Verified that `AGENTS.md` already contains the Shared Agent Context Rule.

### Files changed
- `SHARED.md` (appended this update)

### Important context for the other agent
- No project code changes were made in this step.
- The shared-context workflow is already installed and should continue to be followed.

### Next steps / unfinished work
- Continue using `SHARED.md` as required before and after meaningful work.

## Update - 2026-05-20 14:49 - Codex

### What I did
- Added a Codex-specific startup rule to `AGENTS.md`.
- Clarified that `AGENTS.md` is the project-level instruction hook for Codex and that Codex must read `SHARED.md` first at session start.
- Avoided modifying any Claude-specific configuration.

### Files changed
- `AGENTS.md`
- `SHARED.md`

### Important context for the other agent
- Do not add or modify Claude hooks/settings for this requirement unless the user explicitly asks.
- For Codex, enforce the shared-context workflow through `AGENTS.md`.

### Next steps / unfinished work
- On future Codex sessions, read `SHARED.md` first before planning, inspecting unrelated files, or editing.

## Update - 2026-05-20 15:10 - Claude (Opus 4.7)

### What I did
- Created `src/main_beta.py` as a minimal-diff variant of `src/main.py` that switches both `PoseLandmarker` and `HandLandmarker` from `RunningMode.VIDEO` (blocking `detect_for_video`) to `RunningMode.LIVE_STREAM` (non-blocking `detect_async` + `result_callback`). Goal: reduce perceived camera delay caused by running two synchronous inferences per frame.
- Kept `main.py` untouched so the user can A/B compare.

### Files changed
- `src/main_beta.py` (new)

### Important context for the other agent
- The async results are stored in two module-level globals (`latest_pose_result`, `latest_hand_result`) written from MediaPipe's callback threads. No lock is used — relies on the GIL making single-reference assignment atomic. If callbacks grow to do more than a single assignment, add a `threading.Lock`.
- `main_beta.py` snapshots both globals into locals at the top of each frame before drawing, so a callback firing mid-frame can't swap the object out from under the drawing loop.
- First 1–2 frames render without landmarks (callbacks haven't fired yet) — the `is not None` guards handle this.
- While editing, I noticed two bugs in `main.py`'s cleanup path that would crash on quit: `main.py:109` calls undefined `detector.close()` (should be `pose_detector.close()` + `hand_detector.close()`), and `main.py:110` has `v2.destroyAllWindows()` (typo, missing `c`). I fixed both in `main_beta.py` but **left `main.py` as-is** since the user only asked for the LIVE_STREAM beta.
- Other efficiency levers we discussed but did NOT apply (saved for later iteration): (a) downscale the frame before sending to MediaPipe and scale landmarks back when drawing, (b) run the hand detector every N frames instead of every frame.

### Next steps / unfinished work
- User to test `src/main_beta.py` vs `src/main.py` and compare perceived latency / FPS.
- If LIVE_STREAM helps, fold the changes back into `main.py` and delete `main_beta.py`.
- Independently, fix the two cleanup bugs in `main.py` (`detector.close()` and `v2.destroyAllWindows()`).
