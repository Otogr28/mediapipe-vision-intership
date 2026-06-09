---
title: hints.py
tags: [module, ui, onboarding, overlay]
---

# `hints.py` — Onboarding Overlays

**Location:** `src/ui/hints.py`

Two onboarding overlays plus the shared stylized-hand renderer they use to
demonstrate the pinch gesture. Owned and driven by [[modules/ui_manager]] —
neither class reads detection results directly; the manager feeds them the
small amount of state they need.

---

## `draw_pinch_hand(frame, cx, cy, s, openness)`

Draws a real **21-landmark hand** (MediaPipe's hand topology) posed
mid-pinch and centred at `(cx, cy)`: the middle/ring/pinky fingers are
curled into a loose fist while the index and thumb extend and animate
together. It is rendered as filled rounded capsules between the joints
plus a convex-hull palm, with an outline pass behind the skin pass — the
same skeletal language the app uses to draw live hands, so it reads
unmistakably as a hand.

| Parameter | Meaning |
|---|---|
| `s` | Approximate hand height in pixels |
| `openness` | `0.0` = thumb/index touching, `1.0` = fully open |

The non-animated joints live in the `_HAND_BASE` template (normalised
coords); landmarks 4 (thumb tip) and 8 (index tip) are computed per frame
so only the two pinching fingers move. A glow ring pulses at the pinch
point as the fingers meet, reading as a "tap / select". Reused by both
overlays below so the demo gesture looks identical everywhere. Colours are
BGR (the overlays draw on dark panels).

The animation value comes from `_pinch_openness(start, period)`, a looping
`open → close → open` cosine driven by `time.monotonic()`.

---

## `IntroOverlay`

Startup splash, shown once for `INTRO_DURATION_S` seconds (default 3 s),
Nintendo-style. Dims the live camera, then overlays the title
(`INTRO_TITLE`), subtitle (`INTRO_SUBTITLE`), a large animated pinch hand,
the instruction text (`HINT_TEXT`), and a countdown progress bar. Fades in
and out over `INTRO_FADE_S`.

- `active` → `True` while the splash should still play.
- `draw(frame)` → renders the splash in place; no-op once elapsed.

The whole splash is composited onto a dimmed copy of the frame and blended
back with a single opacity so the fade affects text, hand, and scrim
together.

## `PinchHint`

Bottom-right reminder that appears while a person is detected **and** the
user has not interacted yet. It retires **permanently** under two
conditions, whichever comes first:

1. the user interacts (any button press or grab), or
2. it has been visible for `HINT_TIMEOUT_S` seconds (default 8 s).

Once retired (the internal `_expired` latch), it never shows again for the
life of the session.

- `update(person_detected, has_interacted)` → recomputes visibility / latch.
- `draw(frame)` → semi-transparent panel + animated pinch hand + wrapped
  `HINT_TEXT`. No-op when not visible.

Because reaching any non-menu state requires pressing a menu button (which
sets `has_interacted`), in practice the hint only shows in the `menu` state
before the first interaction — so it never collides with the Reset button.

---

## Related config

`INTRO_DURATION_S`, `INTRO_FADE_S`, `HINT_PINCH_PERIOD_S`, `HINT_TIMEOUT_S`,
`INTRO_TITLE`, `INTRO_SUBTITLE`, `HINT_TEXT` — see [[modules/config]].

See also: [[modules/ui_manager]], [[architecture]]
