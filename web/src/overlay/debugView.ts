/**
 * Shared "skeleton view" flag — a raw-inference debug overlay that draws EVERY
 * tracked point (33 pose + 21×hands) on the live video. Kept in its own module
 * so the Canvas2D rAF loops in overlay/* can read it without
 * React re-rendering them, while App owns the toggle (hotkey `k` / `?skeleton=1`)
 */
let _skeleton = false;

export function isSkeletonView() {
  return _skeleton;
}

export function setSkeletonView(v: boolean) {
  _skeleton = v;
}
