import { FistHand } from "./FistHand";
import { PinchHand } from "./PinchHand";

/**
 * The animated demo hand, posed for whichever gesture the backend is
 * actually watching for (`session.demo_gesture`).
 *
 * One component instead of a hardcoded import at each onboarding site, so
 * flipping HALL_GESTURE can never leave the intro, the greeting and the
 * hint panel demonstrating a gesture the detector ignores.
 *
 * Defaults to the fist, matching config.DEMO_GESTURE's default — a backend
 * predating this field is also a backend that never sent `demo_gesture`, and
 * showing the larger gesture is the safer guess for a mock or an old build.
 */
export function GestureDemo({
  gesture,
  size,
}: {
  gesture?: "pinch" | "fist";
  size?: number;
}) {
  return gesture === "pinch" ? <PinchHand size={size} /> : <FistHand size={size} />;
}
