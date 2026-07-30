import { useEffect, useRef, useState } from "react";
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
import { AimReadout, SlingshotLegend } from "./hud/Slingshot";
import { setSkeletonView } from "./overlay/debugView";
import { OverlayCanvas } from "./overlay/OverlayCanvas";
import type { GalleryObject, SlingshotObject } from "./state/types";
import { useAppState } from "./state/useAppState";

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
  // Raw-inference view: draw every tracked point on the body.
  // `k` toggles it; `?skeleton=1` opens straight into it (handy from the laptop).
  const [showSkeleton, setShowSkeleton] = useState(() =>
    new URLSearchParams(location.search).has("skeleton"),
  );
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
  const gallery = state?.objects.find(
    (o): o is GalleryObject => o.type === "gallery",
  );
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
        <HudLayer frameW={frameW} frameH={frameH}>
          {state && (
            <>
              <Buttons buttons={state.buttons} speed={state.speed} />
              {slingshot && (
                <>
                  <SlingshotLegend />
                  <AimReadout obj={slingshot} />
                </>
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
