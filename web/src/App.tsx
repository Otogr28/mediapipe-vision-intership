import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { LensedVideo } from "./gl/LensedVideo";
import { WavesLayer } from "./gl/WavesLayer";
import { ChargesLayer } from "./gl/ChargesLayer";
import { MagnetsLayer } from "./gl/MagnetsLayer";
import { Attract } from "./hud/Attract";
import { Buttons } from "./hud/Buttons";
import { DebugHud } from "./hud/DebugHud";
import { Gallery } from "./hud/Gallery";
import { Greeting } from "./hud/Greeting";
import { HintPanel } from "./hud/HintPanel";
import { HudLayer } from "./hud/HudLayer";
import { Intro } from "./hud/Intro";
import { SixSeven } from "./hud/SixSeven";
import { AimReadout, SlingshotLegend } from "./hud/Slingshot";
import { AVATARS } from "./gl/avatars";
import { isVrmReady } from "./gl/vrmState";
import { setSkeletonView } from "./overlay/debugView";
import { OverlayCanvas } from "./overlay/OverlayCanvas";
import type {
  GalleryObject,
  SixSevenObject,
  SlingshotObject,
} from "./state/types";
import { useAppState } from "./state/useAppState";

// Lazy so three.js + three-vrm (the biggest dependency) only download when
// the user actually opens Vtuber — the black-hole / orbitals paths stay light.
const VrmAvatar = lazy(() =>
  import("./gl/VrmAvatar").then((m) => ({ default: m.VrmAvatar })),
);

/**
 * Layer stack, bottom to top (all sharing the .stage aspect-ratio box):
 *   <img>          live MJPEG camera frames (already mirrored by the backend)
 *   LensedVideo    WebGL2 black-hole shader — mounted only while one exists
 *   OverlayCanvas  frame-pixel Canvas2D: skeleton, scene objects, cursors
 *   HudLayer       frame-pixel DOM: buttons, panels, onboarding, debug
 *   Attract        opaque idle slideshow — covers everything above
 *   Greeting       translucent hello + gesture demo for a new visitor
 *   Intro          page-load splash (frontend-local clock; attract mode off)
 */
export function App() {
  const { state, connected, pairRef } = useAppState();
  const videoRef = useRef<HTMLImageElement>(null);

  // ?nointro=1 skips the splash (dev/screenshot convenience).
  const [introDone, setIntroDone] = useState(() =>
    new URLSearchParams(location.search).has("nointro"),
  );
  const [showDebug, setShowDebug] = useState(false);
  // Raw-inference view: draw every tracked point on the body, hide the avatar.
  // `k` toggles it; `?skeleton=1` opens straight into it (handy from the laptop).
  const [showSkeleton, setShowSkeleton] = useState(() =>
    new URLSearchParams(location.search).has("skeleton"),
  );
  // `?avatar=N` fallback for local/mock runs whose backend doesn't send
  // session.avatar_index (the real backend always does — see below).
  const urlAvatar = (() => {
    const n = Number(new URLSearchParams(location.search).get("avatar"));
    return Number.isInteger(n) && n >= 0 && n < AVATARS.length ? n : 0;
  })();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "d") setShowDebug((v) => !v);
      if (e.key === "k") setShowSkeleton((v) => !v);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Skeleton view is active from either the frontend toggle (`k` / `?skeleton=1`)
  // OR the backend "Points" pinch button (`session.show_points`) — the latter
  // makes it reachable on the touchless kiosk with no keyboard.
  const skeletonView = showSkeleton || !!state?.session.show_points;

  // Mirror it into the module flag the Canvas2D loops read.
  useEffect(() => {
    setSkeletonView(skeletonView);
  }, [skeletonView]);

  // Attract phase. A backend predating attract mode sends no `phase` at all,
  // which means it is always live — the exhibit behaviour then matches what
  // it was before, rather than a blank screen waiting for a signal that
  // never arrives.
  const phase = state?.session.phase ?? "live";
  const attract = phase === "attract" ? state?.session.attract : null;
  const greeting = phase === "greeting" ? state?.session.greeting : null;
  const demoGesture = state?.session.demo_gesture;

  // The page-load splash is redundant once attract mode is running: the
  // greeting says the same thing per VISITOR instead of per page load, and
  // on a kiosk a page load happens at boot with nobody in the room. Retire
  // it as soon as a backend proves it has phases.
  useEffect(() => {
    if (state?.session.phase) setIntroDone(true);
  }, [state?.session.phase]);

  const frameW = state?.frame.w ?? 1920;
  const frameH = state?.frame.h ?? 1080;

  const sixseven = state?.objects.find(
    (o): o is SixSevenObject => o.type === "sixseven",
  );
  const slingshot = state?.objects.find(
    (o): o is SlingshotObject => o.type === "slingshot",
  );
  const hasBlackHole =
    state?.objects.some((o) => o.type === "black_hole") ?? false;
  const hasWaves = state?.objects.some((o) => o.type === "waves") ?? false;
  const hasCharges =
    state?.objects.some((o) => o.type === "charges") ?? false;
  const hasMagnets =
    state?.objects.some((o) => o.type === "magnets") ?? false;
  const hasVtuber =
    state?.objects.some((o) => o.type === "vtuber") ?? false;
  const gallery = state?.objects.find(
    (o): o is GalleryObject => o.type === "gallery",
  );
  // The backend's "Avatar" pinch button owns which model is shown (rides
  // session.avatar_index); `urlAvatar` only covers mock backends that omit it.
  const avatarIdx = (() => {
    const n = state?.session.avatar_index;
    return typeof n === "number" && n >= 0 && n < AVATARS.length ? n : urlAvatar;
  })();

  return (
    <div className="viewport">
      <div className="stage" style={{ aspectRatio: `${frameW} / ${frameH}` }}>
        {/* Unmounted during attract, not merely covered: dropping the <img>
            closes the MJPEG connection, so the browser stops decoding 30
            frames a second of an empty room behind an opaque slideshow —
            which is what the Orin would otherwise spend most of its day
            doing. It reconnects when the greeting brings the video back. */}
        {phase !== "attract" && (
          <img ref={videoRef} className="layer" src="/stream.mjpg" alt="" />
        )}
        {hasBlackHole && (
          <LensedVideo
            pairRef={pairRef}
            videoRef={videoRef}
            frameW={frameW}
            frameH={frameH}
          />
        )}
        {hasWaves && (
          <WavesLayer pairRef={pairRef} frameW={frameW} frameH={frameH} />
        )}
        {hasCharges && (
          <ChargesLayer pairRef={pairRef} frameW={frameW} frameH={frameH} />
        )}
        {hasMagnets && (
          <MagnetsLayer pairRef={pairRef} frameW={frameW} frameH={frameH} />
        )}
        {/* Below the overlay canvas on purpose: the cursor and the skeleton
            have to draw OVER the photographs, since seeing where the exhibit
            thinks your hand is is the whole feedback loop while dragging. */}
        {gallery && (
          <HudLayer frameW={frameW} frameH={frameH}>
            <Gallery gallery={gallery} />
          </HudLayer>
        )}
        <OverlayCanvas pairRef={pairRef} frameW={frameW} frameH={frameH} />
        {hasVtuber && !skeletonView && (
          <Suspense fallback={null}>
            <VrmAvatar
              key={AVATARS[avatarIdx].src}
              src={AVATARS[avatarIdx].src}
              pairRef={pairRef}
              frameW={frameW}
              frameH={frameH}
            />
          </Suspense>
        )}
        <HudLayer frameW={frameW} frameH={frameH}>
          {state && (
            <>
              <Buttons buttons={state.buttons} speed={state.speed} />
              {sixseven && <SixSeven obj={sixseven} frameW={frameW} />}
              {slingshot && (
                <>
                  <SlingshotLegend />
                  <AimReadout obj={slingshot} />
                </>
              )}
              {hasVtuber && (
                <div
                  className="vtuber-status data"
                  style={{ left: 24, top: frameH - 44 }}
                >
                  <span className={isVrmReady() ? "on" : "off"}>●</span> avatar
                  {"   "}
                  <span className={state.pose ? "on" : "off"}>●</span> body
                </div>
              )}
              {introDone && state.session.hint.visible && (
                <HintPanel
                  frameW={frameW}
                  frameH={frameH}
                  gesture={demoGesture}
                  text={state.session.hint.text}
                />
              )}
              {showDebug && <DebugHud state={state} frameH={frameH} />}
            </>
          )}
        </HudLayer>
        {attract && <Attract attract={attract} />}
        {greeting && <Greeting greeting={greeting} gesture={demoGesture} />}
        {!introDone && (
          <Intro
            onDone={() => setIntroDone(true)}
            gesture={demoGesture}
            hint={state?.session.hint.text}
          />
        )}
        {!connected && (
          <div className="conn-banner">Reconnecting to camera backend…</div>
        )}
      </div>
    </div>
  );
}
