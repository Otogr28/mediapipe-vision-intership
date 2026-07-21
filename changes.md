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

### 2026-07-21 16:03 EDT — Site v2: book prose (no em dashes/arrows), real phone-first responsive, NASA photo replaces the synthetic mock background
**Area:** docs/ (all pages + style.css), web/scripts/mock_backend.py (`HALL_MOCK_BG`), docs/img/*.jpg regenerated
**Status:** VERIFIED HEADLESS — every scene reshot through vite+mock with the new background, 0 console errors; site checked at 1600px and 360px (0 px horizontal overflow, measured); grep confirms 0 em dashes/arrows across docs/ · NOT PUSHED  ·  **Artifact:** `docs/**`, `web/scripts/mock_backend.py`
**Problem:** RESOLVED — `.exp-head > div` (0,1,1) also matched the `.exp-anim` div and its `min-width: min(30rem,100%)` crushed the 84px mobile width, blowing the header SVG up to full-bleed on phones; fixed with `:not(.exp-anim)`. Caught by measuring `getBoundingClientRect` at 360px, not by eyeballing.

**Changes (three operator requests):**
- **Copy rewritten as popular-science book prose.** Em dashes and arrow
  glyphs are BANNED from the site (operator rule, keep it that way):
  sentences restructured with periods, colons and commas; "RELATED →"
  became a "KEEP EXPLORING:" sentence; "← All experiments" became "Back
  to all experiments"; the schrodinger chain reads "the Geiger tube trips
  the hammer, the hammer tips the flask, and the flask decides the cat".
  Verify with `grep -c "—\|→\|←" docs/...` = 0 (CSS comments included).
- **Responsive overhaul, phones first** (QR arrivals): fluid type via
  clamp() on body/h1/h2/lede/captions, auto-fit grids with
  `minmax(min(100%, Xrem), 1fr)` (howto + cards stack without media
  queries), fluid paddings, `color-scheme: dark`, `theme-color` meta,
  text-wrap balance; ≤720px the experiment-header SVG becomes an 84px
  chapter vignette above the title (flex column-reverse).
- **Mock background is now a real open-licensed photo** (operator: no
  self-made test card in site imagery): new `HALL_MOCK_BG=<path>` in
  mock_backend.py cover-crops any photo to the frame (dimmed 0.85, MOCK
  label still gated by `HALL_MOCK_LABEL`). Site images use NASA/STScI's
  public-domain Webb "Cosmic Cliffs" (images.nasa.gov `carina_nebula`,
  1920x1111 `~large.jpg`); credit line added to the index footer. All 7
  docs/img JPEGs regenerated (~260-295 KB each).

**Tests to run:**
- [ ] After the next hallpush: reload the live Pages site on a real phone
      (the QR path) and sanity-check type sizes + the 84px vignettes.
- [ ] Still pending: on-site phone scan of the plates.

### 2026-07-21 15:02 EDT — Site verified LIVE + Pillow CVE batch fixed (post-hallpush follow-up)
**Area:** uv.lock (Pillow bump), verification only otherwise
**Status:** VERIFIED LIVE — Pages build `built` on bd34c85 in 20 s; index, experiment pages, style.css and images all HTTP 200 at https://otogr28.github.io/mediapipe-vision-intership/ (including the exact `/experiments/<key>.html` URLs baked into the QRs); kiosk `/healthz` 200 over Tailscale after the push · SMOKE OK (10/10) · NOT PUSHED (the uv.lock commit rides the next hallpush — kiosk-irrelevant, Jetson doesn't use uv)  ·  **Artifact:** `uv.lock`
**Problem:** RESOLVED (×2) —
1. GitHub flagged **13 Dependabot alerts, ALL Pillow < 12.3.0** (10 high,
   CVE-2026-54058…59205, a June-2026 batch). `uv lock --upgrade-package
   pillow` → 12.3.0 clears every one. Laptop dev env only.
2. **Plain `uv sync` silently strips the `gpu` dependency group** (PEP 735
   `[dependency-groups] gpu = [onnxruntime]` in pyproject.toml — NOT
   installed by default): my sync for the Pillow bump pruned
   onnxruntime AND its protobuf, breaking `import google.protobuf`
   (mediapipe 0.10.35 imports fine without it, so smoke 10/10 masked it).
   Restored with **`uv sync --group gpu`** — use that form on the laptop,
   not bare `uv sync` (CLAUDE.md's command predates the gpu group).

**Tests to run:**
- [ ] Still pending from 14:49: on-site phone scan of the plates at
      visitor distance; `HALL_OUTPUT=window` cv2 QR spot-check.

### 2026-07-21 14:49 EDT — Exhibit website live in docs/ + real QR codes on the plates (executes the 14:07 plan)
**Area:** docs/ (NEW: the exhibit site), web/scripts (gen_qr.py NEW, mock_backend.py), src/ui/manager.py, src/config.py, web/src/overlay/scene.ts, web/src/assets/qr/ (NEW), .gitignore
**Status:** SMOKE OK (10/10) · VERIFIED HEADLESS (mock) — the QR decodes **from the rendered frames of BOTH renderers** (cv2: `cv2.QRCodeDetector` reads the correct per-experiment URL off a synthetic-frame `UIManager.draw()` at 720p, waves AND slingshot keys; web: every scene screenshotted through vite+mock, 0 console errors, waves QR decoded from the screenshot) · DIST REBUILT · NOT PUSHED · **GitHub Pages ENABLED** (gh api: legacy build, `main` `/docs` — builds on the next push)  ·  **Artifact:** `docs/**` (index + 7 experiment pages + style.css + img/*.jpg + .nojekyll), `web/scripts/gen_qr.py`, `web/src/assets/qr/*.png`, `src/ui/manager.py` (`_experiment_qr`/`_draw_qr_plate`), `src/config.py` (`QR_DIR`), `web/src/overlay/scene.ts` (`drawQrPlate`), `web/dist/*`

**Changes:**
- **Real QR codes replace the dashed placeholder.** `web/scripts/gen_qr.py`
  (PEP 723 inline deps → `uv run`, segno never touches the app lockfile)
  renders one PNG per `session.experiment` key → `web/src/assets/qr/` :
  `<base>/experiments/<key>.html`, EC M, byte mode, v5, navy-on-white.
- **Both renderers wired, placeholder kept as fallback** (missing PNG →
  old dashed plate). cv2: `_experiment_qr` caches per (key, side) like
  `_scat_sprite`, key read once per activation via `to_state()["type"]`;
  new `QR_DIR` in config.py. Web: 7 Vite imports (inlined as data URIs,
  <4 kB each) + `QR_IMGS`; `drawQrPlaceholder` renamed **`drawQrPlate`**
  both sides. Quiet zone = plate pad 0.06·side + the PNG's 2-module
  border (comment mirrored in both files).
- **Exhibit site under `docs/`** (static hand-written HTML+CSS, no build
  step; Pages serves it raw; kiosk ignores it): index (what the display
  is, pinch/hold/release how-to, 7-experiment card grid, behind-the-scenes
  + nothing-is-recorded note) + one plain-language page per experiment
  (kiosk verbs, the physics, a "worth knowing" fact, hand-picked related
  links, one inline SVG animation each). Gordon-family theme (navy
  `#0A1724` / cyan `#00B0DC` / white; Space Grotesk + IBM Plex Mono =
  the kiosk HUD voice; signature element = the exhibit's own pinch cursor
  as CSS animation). Responsive (mobile-checked at 390px), reduced-motion
  respected, no Gordon logo/wordmark used.
- Site images = mock screenshots (new `HALL_MOCK_LABEL=0` knob hides the
  MOCK watermark), JPEG q86 → `docs/img/`, ~870 kB total.
- `.gitignore`: `!docs/**` (the global `*.png`/`*.jpg` rules would have
  eaten the site images — same failure class as the dist rule).
- **GitHub Pages enabled NOW** via
  `gh api repos/Otogr28/mediapipe-vision-intership/pages` (main, /docs).
  The remote doesn't have docs/ yet → first real build happens on push.

**Notes:**
- At 480p the plate (~76 px) is below cv2's QR-decode threshold — the
  kiosk captures at 720p (~115 px plate) where it decodes cleanly; phones
  are better detectors than cv2. If the on-site scan test still fails,
  bump `QR_BOX_FRAC` (BOTH sides).
- Mock's `picker` scene only stages 3 experiment buttons (predates the
  7-experiment lineup) — cosmetic, not used for the site.

**Tests to run:**
- [ ] `hallpush` (user) → check the Pages build goes green and
      `https://otogr28.github.io/mediapipe-vision-intership/` serves; then
      confirm the kiosk plates show the codes.
- [ ] **Phone scan test at visitor distance** (the 14:07 checklist's last
      open item): scan each experiment's plate off the kiosk screen; if it
      won't lock, bump `QR_BOX_FRAC` in config.py ↔ scene.ts.
- [ ] `HALL_OUTPUT=window` spot-check of the cv2 QR blit on-device.

### 2026-07-21 14:07 EDT — CONTINUE HERE: exhibit website on GitHub Pages + real QR codes in the plates
**Area:** planning (no code changed — this entry IS the deliverable: the continue plan)
**Status:** NOT STARTED · groundwork verified (repo is PUBLIC → free Pages works; Gordon palette captured)  ·  **Artifact:** this entry + the SHARED.md 14:07 update

**The plan (operator's spec):** replace the QR placeholder plates with REAL
QR codes pointing at a website hosted from THIS repo on GitHub Pages. The
site is the exhibit's public face: a main page explaining the interactive
display, linking to one sub-page per experiment with an explanation written
for people who don't know much physics, with images and animations. Visual
theme: same family as gordon.edu.

**Facts already verified (don't re-derive):**
- Remote is `Otogr28/mediapipe-vision-intership` and it is **PUBLIC**, so
  free GitHub Pages works. Site base URL will be
  `https://otogr28.github.io/mediapipe-vision-intership/`.
- Gordon College brand palette (teamcolorcodes.com; official guide at
  gordon.edu/styleguide): **Dark Navy `#0A1724`** (PMS 296), **Cyan
  `#00B0DC`** (PMS 638), **White**. Design language: clean modern academic,
  image-heavy hero + card grid, strong call-to-action buttons. Use the
  palette/feel only — do NOT copy the Gordon logo/wordmark.
- The 7 experiment keys (`session.experiment` in the state contract):
  `black_hole, slingshot, orbitals, waves, charges, spacetime, schrodinger`.
- `.gitignore` already re-includes `web/src/assets/**` + `web/dist/**`, so
  QR PNGs travel to the Jetson with no further gitignore work.
- The plate geometry to fill: `QR_BOX_FRAC = 0.16` / `QR_MARGIN_FRAC =
  0.03` (config.py ↔ scene.ts), white plate = the QR quiet zone.

**Next (CONTINUE HERE):**
- [ ] **Site skeleton in `docs/`** (static hand-written HTML+CSS, no build
      step — Pages serves it raw; the kiosk ignores `docs/` entirely):
      `docs/index.html` (what the display is, how pinch gestures work, card
      grid linking the 7 experiments) + `docs/experiments/<key>.html` × 7
      (plain-language physics, images, CSS/SVG animations). Screenshots can
      come from the mock (`mock_backend.py <scene>` + `shot.mjs`).
- [ ] **Theme**: navy/cyan/white per the palette above, shared
      `docs/style.css`, responsive (phones — people arrive via QR).
- [ ] **Enable Pages** (one-time): repo Settings → Pages → deploy from
      `main` `/docs`, or
      `gh api repos/Otogr28/mediapipe-vision-intership/pages -f build_type=legacy -f "source[branch]=main" -f "source[path]=/docs"`.
- [ ] **QR generation**: script `web/scripts/gen_qr.py` (add `segno` or
      `qrcode[pil]` as a dev dep) mapping each experiment key →
      `<base>/experiments/<key>.html`, output
      `web/src/assets/qr/<key>.png` (error correction M, white border for
      the quiet zone).
- [ ] **Wire the plates**: cv2 `UIManager._draw_qr_placeholder` blits the
      active experiment's QR (it knows the key via
      `_active_experiment.to_state()["type"]`); web `drawQrPlaceholder`
      takes `session.experiment` and drawImages the imported PNG. Keep the
      dashed placeholder as fallback when the asset is missing.
- [ ] **Scan test**: at 720p the plate is ~115 px — verify a phone scans it
      from visitor distance; if not, bump `QR_BOX_FRAC` (both sides!).
- [ ] Rebuild + commit `web/dist`, then `hallpush` when ready.

### 2026-07-21 13:44 EDT — QR-code placeholder plate, bottom-left of every running experiment
**Area:** src/ui/manager.py, src/config.py (QR_* consts), web/src/overlay/scene.ts
**Status:** SMOKE OK (10/10) · VERIFIED HEADLESS — cv2 path via synthetic-frame UIManager render, web path via mock waves screenshot, plates match · DIST REBUILT · NOT PUSHED  ·  **Artifact:** `src/ui/manager.py` (`_draw_qr_placeholder`), `src/config.py` (`QR_BOX_FRAC`/`QR_MARGIN_FRAC`), `web/src/overlay/scene.ts` (`drawQrPlaceholder`), `web/dist/*`

**Changes:**
- White square plate bottom-left whenever an experiment is RUNNING — the
  spot each experiment's QR code (link to its info page) will occupy.
  Placeholder look until the codes land: white plate, dark border, dashed
  inner square, "QR" centred.
- Implemented ONCE per renderer instead of per scene: cv2 in
  `UIManager.draw()` (experiments branch, right after the experiment so
  buttons/cursor stay on top), web in `drawScene()` gated on
  `session.state === "experiments" && session.experiment` — covers all
  seven experiments including the black hole (GL layer sits below the
  overlay canvas). Picker screen and interactables/vtuber don't show it.
- New hand-mirrored pair `QR_BOX_FRAC = 0.16` / `QR_MARGIN_FRAC = 0.03`
  (config.py ↔ scene.ts, both sides carry the keep-in-sync comment). The
  plate is not a pinch target, so it may sit nearer the border than
  `EDGE_MARGIN_FRAC` allows for interactables.

**Tests to run:**
- [ ] When the real QR codes exist: swap the dashed placeholder for the
      per-experiment code (needs an experiment→URL map + a QR asset or
      client-side generator) and re-check contrast at kiosk distance.
- [ ] Waves/Charges: confirm a source placed near the bottom-left corner
      still reads under the plate (the plate draws over scene pixels).

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
