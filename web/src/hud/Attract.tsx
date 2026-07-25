import type { AttractState } from "../state/types";

/**
 * The idle slideshow, shown while nobody is standing at the exhibit.
 *
 * Full-bleed and opaque on purpose: it covers the camera layer, so an empty
 * room is not broadcast back at the corridor and the screen reads as a
 * display rather than a mirror. Python owns which slide and how far into the
 * cross-fade (`session.attract`), the same way it owns every other scene —
 * the browser only paints it.
 *
 * Every slide is mounted at once and switched by opacity. Swapping the `src`
 * of one <img> would show a blank frame for as long as the next photograph
 * takes to decode, which on the Orin is long enough to see.
 */
export function Attract({ attract }: { attract: AttractState }) {
  const { slides, index, prev, fade } = attract;
  const current = slides[index];

  return (
    <div className="attract">
      {slides.map((slide, i) => (
        <img
          key={slide.src}
          className="attract-photo"
          src={slide.src}
          alt=""
          style={{
            opacity: i === index ? fade : i === prev ? 1 - fade : 0,
          }}
        />
      ))}

      <div className="attract-scrim" />

      <div className="attract-caption">
        <div className="attract-eyebrow label">{attract.title}</div>
        {current && (
          <>
            <div className="attract-title">{current.title}</div>
            {current.caption && (
              <div className="attract-sub">{current.caption}</div>
            )}
          </>
        )}
        <div className="attract-prompt label">{attract.prompt}</div>
      </div>

      <div className="attract-dots">
        {slides.map((slide, i) => (
          <span
            key={slide.src}
            className={i === index ? "dot on" : "dot"}
          />
        ))}
      </div>
    </div>
  );
}
