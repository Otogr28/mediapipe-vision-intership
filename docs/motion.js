// The demo clips on these pages (docs/img/*.mp4) are silent loops of the
// display running each experiment. They carry preload="none" and no autoplay,
// so nothing is fetched until a clip is actually near the viewport: the page
// opens on the poster stills, exactly as it did when they were plain images.
//
// A visitor who asked their system for less motion keeps the stills.
(() => {
  const clips = [...document.querySelectorAll("video[data-demo]")];
  if (!clips.length || !("IntersectionObserver" in window)) return;

  const calm = matchMedia("(prefers-reduced-motion: reduce)");
  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting && !calm.matches) {
          // play() rejects on some mobile power-saving modes; the poster
          // stays up in that case, which is a fine outcome.
          entry.target.play().catch(() => {});
        } else {
          entry.target.pause();
        }
      }
    },
    { rootMargin: "150px 0px" },
  );

  clips.forEach((clip) => observer.observe(clip));
  calm.addEventListener("change", () => {
    if (calm.matches) clips.forEach((clip) => clip.pause());
  });
})();
