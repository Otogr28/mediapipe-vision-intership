/**
 * Tiny shared flag for the VRM avatar's readiness, kept in its OWN module so
 * the Canvas fallback (overlay/scene.ts) can query it WITHOUT statically
 * importing VrmAvatar.tsx — that keeps three.js / three-vrm out of the main
 * bundle so they load lazily only when Vtuber is selected (see App.tsx).
 */
let _ready = false;

export function isVrmReady() {
  return _ready;
}

export function setVrmReady(v: boolean) {
  _ready = v;
}
