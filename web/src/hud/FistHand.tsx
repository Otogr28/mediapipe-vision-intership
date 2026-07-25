/**
 * Animated whole-hand-closing demo — the fist counterpart of PinchHand.
 *
 * Same drawing language (glass fill + ink outline) and the same 2.4 s cycle
 * with a dwell at the closed pose, so the two demos are interchangeable
 * wherever onboarding shows one. What differs is what the picture asks for:
 * four fingers fold into the palm at their knuckles and the thumb closes
 * across them, which reads from across a hall in a way two fingertips
 * meeting does not.
 *
 * The fingers fold by scaling toward their own base rather than rotating.
 * A rotated bar of finger length sweeps out past the wrist at the angles a
 * real fist needs; scaling to a stub over a row of knuckles that never move
 * lands on the same silhouette without the detour.
 *
 * The cursor ring sits on the PALM, matching where the app's real cursor is
 * anchored in fist mode (gestures.FIST_CURSOR_LANDMARK) — a visitor should
 * recognize the same ring on their own hand a second later.
 *
 * Animation is pure CSS (see styles.css, .fh-*); reduced-motion users get
 * the static closed pose.
 */
export function FistHand({ size = 130 }: { size?: number }) {
  return (
    <svg
      className="fist-hand"
      width={size}
      height={size * 1.2}
      viewBox="38 22 168 202"
      aria-hidden="true"
    >
      {/* Four fingers, each folding toward its own knuckle. Drawn BEFORE
          the palm so a folded finger tucks behind it. */}
      <g className="fh-finger fh-pinky">
        <rect className="fh-body" x="59" y="64" width="19" height="62" rx="9.5" />
      </g>
      <g className="fh-finger fh-ring">
        <rect className="fh-body" x="83" y="46" width="20" height="78" rx="10" />
      </g>
      <g className="fh-finger fh-middle">
        <rect className="fh-body" x="108" y="36" width="20" height="88" rx="10" />
      </g>
      <g className="fh-finger fh-index">
        <rect className="fh-body" x="133" y="48" width="20" height="78" rx="10" />
      </g>

      {/* Palm — narrowed toward the wrist so the silhouette reads as a hand
          rather than a rounded box with fingers glued on. */}
      <path
        className="fh-body"
        d="M 54 140
           C 54 122, 62 112, 80 112
           L 134 112
           C 152 112, 158 122, 158 140
           L 158 184
           C 158 206, 146 216, 124 216
           L 88 216
           C 66 216, 56 204, 54 184
           Z"
      />

      {/* Knuckle row: the detail that makes the closed pose read as a fist
          rather than a plain rounded box. */}
      <g className="fh-knuckles">
        <circle cx="68" cy="128" r="4.5" />
        <circle cx="93" cy="123" r="5" />
        <circle cx="118" cy="122" r="5" />
        <circle cx="143" cy="126" r="4.5" />
      </g>

      {/* Thumb — rotates at its base (158, 188). Open it splays out to the
          right; closed it lies diagonally across the upper palm, which is
          where a thumb actually goes on a real fist (over the folded
          fingers, above the palm's centre). */}
      <g className="fh-thumb">
        <rect className="fh-body" x="148" y="120" width="20" height="72" rx="10" />
      </g>

      {/* Cursor-ring affordance low on the palm, clear of the closed thumb:
          base ring, progress arc (dasharray = 2*pi*15 ≈ 94.2) and one click
          ripple. */}
      <g className="fh-ring-group">
        <circle className="fh-ring-base" cx="106" cy="186" r="15" />
        <circle
          className="fh-ring-progress"
          cx="106"
          cy="186"
          r="15"
          transform="rotate(-90 106 186)"
        />
        <circle className="fh-ripple" cx="106" cy="186" r="15" />
      </g>
    </svg>
  );
}
