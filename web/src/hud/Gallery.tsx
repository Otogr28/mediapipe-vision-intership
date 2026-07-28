import type { GalleryObject } from "../state/types";

/**
 * The photo gallery strip (`ui/gallery.py`).
 *
 * Python owns everything: which photographs exist, where the strip is, and
 * the card rect. This lays card `i` out at `card.x + (i - position) * stride`
 * and paints it — the same arithmetic `Gallery.card_rect` does for the cv2
 * renderer, which is the contract the two share.
 *
 * Mounted BELOW the overlay canvas on purpose. The cursor and the skeleton
 * have to draw over the photographs: the one thing a visitor needs while
 * dragging is to see where the exhibit thinks their hand is.
 *
 * Only the windowed slides are mounted, so the DOM holds five <img> elements
 * whether the folder has eight photographs or eight hundred. React keys them
 * by `src`, so a card that survives a scroll keeps its decoded image instead
 * of being torn down and re-fetched.
 *
 * Text offsets below the card are mirrored by hand from
 * `Gallery.draw` — grep GALLERY_CARD_TOP_FRAC if you move either.
 */
export function Gallery({ gallery }: { gallery: GalleryObject }) {
  const [cx, cy, cw, ch] = gallery.card;
  const { position, index, count, stride, slides } = gallery;
  const below = cy + ch;
  const current = slides.find((s) => s.index === index);

  // A fragment, not a wrapper: `.hud-layer > *` is what makes each of these
  // absolutely positioned in frame pixels, and a wrapper div would put them
  // inside a zero-sized box instead.
  return (
    <>
      <div className="gallery-scrim" />

      <div className="gallery-hint label" style={{ top: cy - 34 }}>
        Close your hand and drag to browse
      </div>

      {slides.map((slide) => (
        <img
          key={slide.src}
          className={
            slide.index === index ? "gallery-card current" : "gallery-card"
          }
          src={slide.src}
          alt=""
          decoding="async"
          style={{
            left: cx + (slide.index - position) * stride,
            top: cy,
            width: cw,
            height: ch,
          }}
        />
      ))}

      {current?.title && (
        <div className="gallery-title" style={{ top: below + 14 }}>
          {current.title}
        </div>
      )}
      <div
        className="gallery-count label"
        style={{ top: below + (current?.title ? 52 : 16) }}
      >
        {count > 0
          ? `${index + 1} / ${count}`
          : "No photographs in the gallery folder"}
      </div>
    </>
  );
}
