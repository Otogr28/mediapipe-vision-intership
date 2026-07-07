/**
 * Animated pinch-gesture demo hand — replaces the cv2 capsule-bone hand
 * from src/ui/hints.py.
 *
 * A stylized diagram hand (glass fill + ink outline, matching the
 * instrument design language) with two articulated groups: the index
 * finger rotates at its knuckle and the thumb at its base. The timing is
 * the important fix over the old cosine loop: the cycle DWELLS in the
 * closed position (~0.7 s) so the "pinch and hold" moment is unmissable.
 *
 * The app's real cursor affordance rides the pinch point: a ring whose
 * arc fills amber during the close, turns green on contact and emits one
 * click ripple — users then recognize the exact same ring on their own
 * hand. Animation is pure CSS (see styles.css, .ph-*); reduced-motion
 * users get the static closed pose.
 */
export function PinchHand({ size = 130 }: { size?: number }) {
  // viewBox cropped to the drawing's bounds (with a little animation
  // headroom) so the hand centres cleanly inside flex parents.
  return (
    <svg
      className="pinch-hand"
      width={size}
      height={size * 1.45}
      viewBox="52 24 136 196"
      aria-hidden="true"
    >
      {/* Palm + three curled fingers: one static silhouette. The bumps
          along the top-left edge read as folded knuckles. */}
      <path
        className="ph-body"
        d="M 72 214
           C 62 178, 60 146, 72 124
           C 76 116, 82 110, 90 106
           C 88 96, 96 90, 104 94
           C 104 84, 114 80, 120 88
           C 122 82, 132 82, 134 90
           L 136 104
           C 142 112, 146 124, 146 140
           C 146 168, 142 192, 138 214
           Z"
      />
      {/* Index finger — rotates at its knuckle (118, 108). */}
      <g className="ph-index">
        <path
          className="ph-body"
          d="M 110 112
             C 108 90, 112 62, 120 44
             C 123 37, 133 37, 136 44
             C 140 62, 138 92, 132 114
             Z"
        />
      </g>
      {/* Thumb — rotates at its base (134, 152). */}
      <g className="ph-thumb">
        <path
          className="ph-body"
          d="M 128 158
             C 136 140, 150 118, 162 104
             C 168 97, 178 104, 175 112
             C 168 130, 152 152, 138 166
             Z"
        />
      </g>
      {/* Cursor-ring affordance at the pinch point: base ring, progress
          arc (dasharray = 2*pi*13 ≈ 81.7) and one click ripple. */}
      <g className="ph-ring-group">
        <circle className="ph-ring-base" cx="152" cy="56" r="13" />
        <circle
          className="ph-ring-progress"
          cx="152"
          cy="56"
          r="13"
          transform="rotate(-90 152 56)"
        />
        <circle className="ph-ripple" cx="152" cy="56" r="13" />
      </g>
    </svg>
  );
}
