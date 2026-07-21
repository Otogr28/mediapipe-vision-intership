# changes.md — Chronological change log (HalLMediaPipe)

Chronological summary of everything that changes in this repo: Python backend
(`src/` — detection, gestures, UI state machine, scenes), web frontend
(`web/src/` + the committed `web/dist`), GPU rendering (`rendering/`), deploy
kit (`deploy/`), docs (`documentation/`), and every time a **new problem
appears** or a **problem is resolved**. A hook reminds you automatically
whenever you touch a repo file (see `.claude/hooks/changes-reminder.sh`), and a
strict Stop gate (`.claude/hooks/changes-stop-gate.sh`) blocks the turn from
ending until you log it. Writing the entry is your job.

This does **not** replace `SHARED.md` (the agent coordination file — context,
warnings and next steps for other agents; keep updating it too) nor the deep
technical docs in `documentation/` (architecture, module contracts, gesture
math). This is the **chronological summary** and the **tests to run**; the
"why" lives in `documentation/` and the hand-off context in `SHARED.md`.
History older than this file lives in `git log` and `SHARED.md`.

## How to write an entry (anti-overwrite rule)

- **NEVER edit or delete entries from other sessions. You only add yours.**
- Your entry goes at the **very top** of the «Entries» section (most recent first),
  right below the `## Entries` heading.
- Head each entry with the **exact date and time** — run
  `date "+%Y-%m-%d %H:%M %Z"` — a **short title**, and follow the template below.
- **One entry per batch of changes** (not one per file). If a problem appeared or
  was resolved in the same batch, say so in that same entry.
- **All entries in English.**
- **Mark the status clearly** using this project's vocabulary:
  - Logic/scenes: `VERIFIED HEADLESS (mock)` (mock_backend + shot.mjs) ·
    `SMOKE OK` (`tests/smoke_scenes.py`) · `NOT VERIFIED`
  - Web frontend: `DIST REBUILT` (npm run build + `web/dist` committed) ·
    `DIST NOT REBUILT` — **a `web/src` change without a rebuilt dist never
    reaches the exhibit**
  - Deploy: `PUSHED` (the kiosk auto-deploys from `main` in ~60 s — say so
    deliberately) · `NOT PUSHED` · `VERIFIED ON JETSON` · `PENDING JETSON TEST`
- If the entry is about a problem, add a `**Problem:**` line with
  `NEW` / `RESOLVED` / `ONGOING`.
- If you touched the state contract, the entry must name **both** sides
  (`src/web/state.py` **and** `web/src/state/types.ts`); if you touched a
  mirrored constant (Waves/Charges/Black hole/Spacetime tables in CLAUDE.md),
  name both files there too.

### Template

```
### YYYY-MM-DD HH:MM TZ — <short title>
**Area:** <src/ui | src/detection | web/src | rendering | deploy | documentation | tests | ...>
**Status:** <VERIFIED HEADLESS (mock) · SMOKE OK · NOT VERIFIED · DIST REBUILT · DIST NOT REBUILT · PUSHED · NOT PUSHED · VERIFIED ON JETSON · PENDING JETSON TEST>  ·  **Artifact:** <files/dirs touched>
**Problem:** <NEW · RESOLVED · ONGOING>   (omit if the entry is not about a problem)

**Changes:**
- <what changed and why>

**Tests to run:**
- [ ] <verification step: uv run python web/scripts/mock_backend.py <scene> + node web/scripts/shot.mjs ... | uv run python tests/smoke_scenes.py | cd web && npm run build (+ commit web/dist) | on-Jetson check after push | HALL_DEBUG=1 live pass ...>
```

---

## Entries

### 2026-07-21 13:13 EDT — Quantum Cat copy pass + big ALIVE/DEAD verdict banner
**Area:** src/ui (SchrodingerCat captions + revealed draw), web/src/overlay/scene.ts, web/scripts/mock_backend.py
**Status:** SMOKE OK (10/10) · VERIFIED HEADLESS (mock) — armed + revealed-alive screenshots inspected, captions confirmed via SSE · DIST REBUILT · NOT PUSHED  ·  **Artifact:** `src/ui/interactables.py`, `web/src/overlay/scene.ts`, `web/scripts/mock_backend.py`, `web/dist/*`
**Problem:** RESOLVED — a stale mock_backend from an earlier verification round kept port 8092 and served old captions, making the new copy look unapplied; killed by PID (pkill's exit-144 self-match had skipped it — see the shell-gotchas memory) and re-verified fresh.

**Changes:**
- **Captions rewritten in plain language** (operator: the post-drop text was
  hard to understand). One instruction per phase, physics jargon out:
  "Now pinch the FIRE button: shoot the alpha particle at the box",
  "Closed box: the cat is alive AND dead at the same time. Pinch it to
  look", etc. Python `CAPTIONS` + mock mirrors.
- **Verdict banner** (operator request): big **ALIVE** in green /
  **DEAD** in red drawn above the box in the revealed phase, dark outline
  for contrast on any camera background, slight pop while the collapse
  flash decays. Implemented in BOTH renderers (cv2 + canvas), placed above
  the open lid flap so nothing overlaps it.

**Tests to run:**
- [ ] On-camera: banner legibility against a real busy background.
- [ ] Kiosk distance check of the new caption copy once pushed.

### 2026-07-21 12:37 EDT — `hallpush`: one command to deploy to the Jetson (add + commit + pull-rebase + push + synca)
**Area:** deploy/hall-app (`hallpush` NEW, README), `~/.local/bin/hallpush` symlink (laptop-local)
**Status:** DONE (`--dry-run` and `-h` exercised from fish; the mutating path deliberately NOT run — the repo holds the unpushed Quantum Cat v2 batch and pushing deploys) · NOT PUSHED  ·  **Artifact:** `deploy/hall-app/hallpush`, `deploy/hall-app/README.md`
**Changes:**
- New `hallpush [-w|--wait] [-n|--no-sync] [--dry-run] [mensaje...]`: commits
  everything (message = args, or a synca-style auto message), `pull --rebase`
  then pushes `main` (the kiosk self-deploys in ~60 s), then runs `synca` so
  the parent vault records the new submodule pointer (repos.conf already
  orders submodule-before-parent). `-w` polls the Jetson over Tailscale SSH
  until it reports the pushed commit and probes the kiosk's `/healthz`.
- Same safety doctrine as synca: never `--force`; a conflicted rebase is
  aborted (repo left clean) and reported. Refuses to run off `main` (only
  `main` deploys). Target overridable via `HALLPUSH_JETSON`/`HALLPUSH_HEALTH`.
- Installed per the vault convention (script lives in the repo, symlinked
  into `~/.local/bin`, so the live command backs itself up); README's Deploy
  section now leads with appliance-mode `hallpush` and demotes `deploy.sh`
  to the manual-rsync path.

**Tests to run:**
- [ ] First real run: `hallpush -w quantum cat v2` — must commit this batch,
      push, synca the vault, and report the Jetson on the new commit.
- [ ] Conflict path when it ever happens: verify the rebase abort leaves the
      tree clean (mirrors synca's behaviour, untested live).

### 2026-07-21 12:21 EDT — Quantum Cat v2: 1935 apparatus with CC0 sprites, alpha gun replaces the slingshot
**Area:** src/ui (SchrodingerCat), src/config.py, web/src (scene.ts + types.ts + assets/schrodinger/), web/scripts/mock_backend.py, tests, documentation, .gitignore
**Status:** SMOKE OK (10/10 scenes, rewritten schrodinger walk) · VERIFIED HEADLESS (mock) — all 4 phases + both outcomes screenshot-inspected, no console errors · DIST REBUILT · NOT PUSHED  ·  **Artifact:** `web/src/assets/schrodinger/*.png` (+CREDITS.md), `src/ui/interactables.py`, `web/src/overlay/scene.ts`, `web/src/state/types.ts`, `web/dist/*`
**Problem:** RESOLVED — the global `*.png` gitignore rule would have silently dropped both the sprite sources AND Vite's emitted `web/dist/assets/*.png` (same failure class as the old `dist/` rule); added `!web/src/assets/**` + `!web/dist/**` negations and verified with `git check-ignore`.

**Changes:**
- **Scene restaged as Schrodinger's actual 1935 thought experiment** (steel
  riveted chamber, Geiger tube on the wall, relay hammer under the radiation
  sign, HCN flask inside — all visible while placing the cat), per the
  operator's ask to research the original and get closer to it.
- **Slingshot emitter removed** (operator: unintuitive): the particle now
  comes from a CC0 ray-gun sprite whose muzzle is level with the Geiger tube;
  a **text-labelled FIRE button** under the grip is the whole interaction —
  pinch it, one alpha particle flies straight at the tube, recoil + muzzle
  flash. No aiming, no misses. Contract fields `emitter/detector/aiming/pull`
  replaced by `gun/gun_w/trigger/trigger_r/geiger/geiger_r/recoil` (both
  sides: `to_state()` and `types.ts`; mock updated).
- **CC0 cartoon sprites** extracted from Wikimedia Commons (Christian
  Schirm's "Schroedingers cat box/experiment" SVGs, CC0) + FreeSVG ray gun:
  alive cat, dead cat, gun, hammer device, flask intact/tipped — rendered by
  BOTH renderers (Vite imports; cv2 `_scat_blit` with per-width cache and
  vector-cat fallback if PNGs are missing). Credits in
  `web/src/assets/schrodinger/CREDITS.md`.
- Superposed phase is now a cutaway showing **both branches** ghosted in
  counter-phase (alive+intact flask vs dead+tipped flask); revealed-dead adds
  rising HCN wisps. Dice still roll on the OPEN pinch (measurement = look).
- Captions rewritten for the apparatus; smoke test walk rewritten
  (trigger fire + recoil + horizontal-shot assert). Docs section in
  `documentation/modules/interactables.md` rewritten.

**Tests to run:**
- [ ] On-camera pass: pinch-drag the cat, FIRE button reach (trigger sits at
      ~0.28W/0.67H — inside EDGE_MARGIN_FRAC, but confirm with real hands).
- [ ] After push: confirm the sprites render on the Jetson kiosk (first git
      pull carries the new dist PNGs).
- [ ] `HALL_OUTPUT=window` spot-check of the cv2 sprite path (blit + fallback).

### 2026-07-21 11:37 EDT — This change log + its enforcing hooks (mirrors the vault-root discipline)
**Area:** repo tooling (`changes.md`, `.claude/hooks/`, `.claude/settings.json`)
**Status:** DONE (hooks exercised with simulated payloads, 9/9 cases pass) · NOT PUSHED  ·  **Artifact:** `changes.md` (this file), `.claude/hooks/changes-reminder.sh`, `.claude/hooks/changes-stop-gate.sh`, `.claude/settings.json`
**Problem:** RESOLVED — the SessionStart hook in `.claude/settings.json` pointed at the repo's old path (`/home/oto/Intership2026/HalLMediaPipe`), so every session was told "SHARED.md not found" even though it exists; it now resolves via `$CLAUDE_PROJECT_DIR`.

**Changes:**
- Created this `changes.md` following the format of the vault-root and
  `CircuitsSimulations` logs, with a status vocabulary adapted to this repo
  (mock/smoke verification, the dist-rebuild rule, push = auto-deploy to the
  kiosk, Jetson testing) and reminders for the hand-mirrored contracts
  (state payload, scene constants).
- Adapted both hooks from the vault root: `changes-reminder.sh` (PostToolUse
  on Write|Edit) flags any file **inside** HalLMediaPipe except `SHARED.md`,
  `web/dist/`, gitignored artifacts (`models/`, `.trt_cache/`) and env/vcs
  dirs; `changes-stop-gate.sh` (Stop) blocks the turn once until the entry is
  written. Marker namespaced as `hall-changes-pending.$sid` so it never
  collides with the vault-root gate.
- Wired both into `.claude/settings.json`, preserving the existing
  SessionStart SHARED.md loader and fixing its stale absolute path.
- Note: hooks are snapshotted at session start, so enforcement begins with
  the **next** session.

**Tests to run:**
- [ ] Next session: touch any `src/` file, try to stop without logging — the
      gate must block once with the adapted message.
- [ ] Next session start: the SHARED.md content must appear in context
      (instead of the "not found" message this session got).
