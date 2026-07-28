import type { AttractSlide, AttractState } from "../state/types";

/**
 * Above this many slides the position dots become a smear along the edge and
 * a counter says the same thing in the same space.
 * KEEP IN SYNC with config.ATTRACT_MAX_DOTS (the cv2 renderer switches at the
 * same count, in ui/attract.py's AttractScreen.draw).
 */
const MAX_DOTS = 12;

/**
 * The idle slideshow, shown while nobody is standing at the exhibit.
 *
 * Full-bleed and opaque on purpose: it covers the camera layer, so an empty
 * room is not broadcast back at the corridor and the screen reads as a
 * display rather than a mirror. Python owns which slide and how far into the
 * cross-fade (`session.attract`), the same way it owns every other scene —
 * the browser only paints it.
 *
 * At most THREE <img> elements are mounted, and they are rendered as a KEYED
 * array so React matches them across renders by `src` rather than by
 * position. That is what makes the preload work: the photograph mounted at
 * zero opacity as `next` is the same DOM node — already fetched and decoded —
 * that becomes `current` one slide later, so the cut never shows the blank
 * frame a fresh JPEG decode would cost on the Orin. Mounting the whole folder
 * instead (what this used to do) would have the browser holding eighty
 * decoded photographs in an 8 GB machine it shares with the inference stack.
 */
export function Attract({ attract }: { attract: AttractState }) {
  const { current, previous, next, fade, index, count } = attract;

  // previous first so it sits UNDER the one fading in; `next` rides on top at
  // zero opacity, where it is invisible either way. A slide reached from two
  // roles at once (a two-photograph folder makes `next` and `previous` the
  // same file) is kept once, under the role that is actually visible.
  const layers: Array<{ slide: AttractSlide; opacity: number }> = [];
  const add = (slide: AttractSlide | null, opacity: number) => {
    if (slide && !layers.some((l) => l.slide.src === slide.src)) {
      layers.push({ slide, opacity });
    }
  };
  add(previous, 1 - fade);
  add(current, fade);
  add(next, 0);

  return (
    <div className="attract">
      {layers.map(({ slide, opacity }) => (
        <img
          key={slide.src}
          className="attract-photo"
          src={slide.src}
          alt=""
          // A slide that is not ready yet must never block the compositor —
          // the cross-fade clock runs in Python and does not wait.
          decoding="async"
          style={{ opacity }}
        />
      ))}

      <div className="attract-scrim" />

      <div className="attract-caption">
        {current?.title ? (
          <>
            <div className="attract-eyebrow label">{attract.title}</div>
            <div className="attract-title">{current.title}</div>
            {current.caption && (
              <div className="attract-sub">{current.caption}</div>
            )}
          </>
        ) : (
          // A gallery photograph has no title of its own, so the name of the
          // exhibit takes the headline slot rather than leaving it empty.
          <div className="attract-title">{attract.title}</div>
        )}
        <div className="attract-prompt label">{attract.prompt}</div>
      </div>

      {count > 1 &&
        (count > MAX_DOTS ? (
          <div className="attract-count label">
            {index + 1} / {count}
          </div>
        ) : (
          <div className="attract-dots">
            {Array.from({ length: count }, (_, i) => (
              <span key={i} className={i === index ? "dot on" : "dot"} />
            ))}
          </div>
        ))}
    </div>
  );
}
