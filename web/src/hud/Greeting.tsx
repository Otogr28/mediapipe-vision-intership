import { GestureDemo } from "./GestureDemo";
import type { GreetingState } from "../state/types";

/**
 * The few seconds after somebody walks up: a hello and one demonstration of
 * the gesture that drives everything.
 *
 * Deliberately translucent rather than opaque — the visitor sees themselves
 * arrive behind the instructions, which is the moment that tells them the
 * screen is reacting to *them* and not playing a video on a loop.
 *
 * The progress bar is driven off `greeting.t` from the backend rather than a
 * CSS animation, because the backend can end the greeting early (a visitor
 * who makes the gesture skips ahead) and a bar that kept filling on its own
 * clock would disagree with what just happened.
 */
export function Greeting({
  greeting,
  gesture,
}: {
  greeting: GreetingState;
  gesture?: "pinch" | "fist";
}) {
  const progress = Math.min(greeting.t / greeting.duration, 1);

  return (
    <div className="greeting">
      <div className="greeting-title label">{greeting.title}</div>
      <div className="greeting-sub">{greeting.subtitle}</div>
      <GestureDemo gesture={gesture} size={190} />
      <div className="greeting-hint label">{greeting.hint}</div>
      <div className="greeting-bar">
        <div
          className="greeting-bar-fill"
          style={{ width: `${progress * 100}%` }}
        />
      </div>
    </div>
  );
}
