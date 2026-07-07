import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { LensedVideo } from "./gl/LensedVideo";
import { Buttons } from "./hud/Buttons";
import { DebugHud } from "./hud/DebugHud";
import { HintPanel } from "./hud/HintPanel";
import { HudLayer } from "./hud/HudLayer";
import { Intro } from "./hud/Intro";
import { SixSeven } from "./hud/SixSeven";
import { AimReadout, SlingshotLegend } from "./hud/Slingshot";
import { OverlayCanvas } from "./overlay/OverlayCanvas";
import type { SixSevenObject, SlingshotObject } from "./state/types";
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
 *   Intro          page-load splash (frontend-local clock)
 */
export function App() {
  const { state, connected, pairRef } = useAppState();
  const videoRef = useRef<HTMLImageElement>(null);

  // ?nointro=1 skips the splash (dev/screenshot convenience).
  const [introDone, setIntroDone] = useState(() =>
    new URLSearchParams(location.search).has("nointro"),
  );
  const [showDebug, setShowDebug] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "d") setShowDebug((v) => !v);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

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
  const hasVtuber =
    state?.objects.some((o) => o.type === "vtuber") ?? false;

  return (
    <div className="viewport">
      <div className="stage" style={{ aspectRatio: `${frameW} / ${frameH}` }}>
        <img ref={videoRef} className="layer" src="/stream.mjpg" alt="" />
        {hasBlackHole && (
          <LensedVideo
            pairRef={pairRef}
            videoRef={videoRef}
            frameW={frameW}
            frameH={frameH}
          />
        )}
        <OverlayCanvas pairRef={pairRef} frameW={frameW} frameH={frameH} />
        {hasVtuber && (
          <Suspense fallback={null}>
            <VrmAvatar pairRef={pairRef} frameW={frameW} frameH={frameH} />
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
              {introDone && state.session.hint.visible && (
                <HintPanel frameW={frameW} frameH={frameH} />
              )}
              {showDebug && <DebugHud state={state} frameH={frameH} />}
            </>
          )}
        </HudLayer>
        {!introDone && <Intro onDone={() => setIntroDone(true)} />}
        {!connected && (
          <div className="conn-banner">Reconnecting to camera backend…</div>
        )}
      </div>
    </div>
  );
}
