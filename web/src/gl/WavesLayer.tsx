import { useEffect, useRef } from "react";
import { interpolate } from "../state/interp";
import type { SnapshotPair } from "../state/useAppState";
import type { WavesObject } from "../state/types";
import stepSrc from "./waves_step.frag.glsl?raw";
import renderSrc from "./waves_render.frag.glsl?raw";
import vertSrc from "./fullscreen.vert.glsl?raw";

interface Props {
  pairRef: React.RefObject<SnapshotPair | null>;
  frameW: number;
  frameH: number;
}

/** Frame pixels per sim cell — the FDTD grid is frame/4 (320x180 at 720p). */
const GRID_PX = 4;
/** CFL safety factor: substep dt <= 0.6 * dx / c. */
const CFL = 0.6;
/** Field ring-down time constant (s) — mirrors config.WAVE_DECAY_TAU_S. */
const DECAY_TAU_S = 1.6;
/** Source onset ramp (s) — mirrors config.WAVE_RAMP_S. */
const RAMP_S = 0.3;
/** Max substeps per rAF, so a background tab can't spiral on resume. */
const MAX_STEPS = 12;

/**
 * The Waves layer: a transparent WebGL2 canvas over the video that
 * integrates the damped 2D wave equation in a ping-pong RG16F texture
 * (one texel per sim cell) and displays it as a translucent water tint.
 * All wave physics EMERGES from the grid: circular fronts, two-source
 * interference, reflection off the frame edges (clamped sampling =
 * Neumann walls), and Doppler wakes when a source is dragged.
 *
 * Python owns the sources (this component only reads them from the state
 * snapshots); the field is presentation, so its sim clock free-runs at
 * `time_scale` and is gently pulled toward the backend's experiment clock
 * to keep source phases aligned. Mount ONLY while a waves experiment is
 * active — unmounted, the GPU does zero work.
 */
export function WavesLayer({ pairRef, frameW, frameH }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const simW = Math.ceil(frameW / GRID_PX);
  const simH = Math.ceil(frameH / GRID_PX);

  useEffect(() => {
    const canvas = canvasRef.current!;
    const gl = canvas.getContext("webgl2", {
      alpha: true,
      antialias: false,
      preserveDrawingBuffer: false,
    });
    if (!gl) {
      console.error("WebGL2 unavailable — waves field disabled");
      return;
    }
    if (!gl.getExtension("EXT_color_buffer_float")) {
      console.error("EXT_color_buffer_float missing — waves field disabled");
      return;
    }

    const compile = (type: number, src: string) => {
      const shader = gl.createShader(type)!;
      gl.shaderSource(shader, src);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
        throw new Error(gl.getShaderInfoLog(shader) ?? "shader compile failed");
      }
      return shader;
    };
    const link = (frag: string) => {
      const program = gl.createProgram()!;
      gl.attachShader(program, compile(gl.VERTEX_SHADER, vertSrc));
      gl.attachShader(program, compile(gl.FRAGMENT_SHADER, frag));
      gl.linkProgram(program);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
        throw new Error(gl.getProgramInfoLog(program) ?? "program link failed");
      }
      return program;
    };
    const stepProg = link(stepSrc);
    const renderProg = link(renderSrc);

    // Fullscreen triangle (shared by both passes).
    const vao = gl.createVertexArray();
    gl.bindVertexArray(vao);
    const vbo = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 3, -1, -1, 3]),
      gl.STATIC_DRAW,
    );
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);

    // Ping-pong field textures: RG16F, .r = u(t), .g = u(t-dt), zeroed.
    // LINEAR filtering serves the display pass; the step pass texelFetches.
    const makeField = () => {
      const tex = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.texStorage2D(gl.TEXTURE_2D, 1, gl.RG16F, simW, simH);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      const fbo = gl.createFramebuffer();
      gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
      gl.framebufferTexture2D(
        gl.FRAMEBUFFER,
        gl.COLOR_ATTACHMENT0,
        gl.TEXTURE_2D,
        tex,
        0,
      );
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      return { tex, fbo };
    };
    let curr = makeField();
    let next = makeField();

    const su = (name: string) => gl.getUniformLocation(stepProg, name);
    const uField = su("u_field");
    const uSim = su("u_sim");
    const uS2 = su("u_s2");
    const uDelta = su("u_delta");
    const uTime = su("u_time");
    const uCount = su("u_count");
    const uSources = su("u_sources");
    const uAmp = su("u_amp");
    const uRamp = su("u_ramp");
    const uRenderField = gl.getUniformLocation(renderProg, "u_field");

    const srcArr = new Float32Array(6 * 4);

    // Sim clock: seeded from the first snapshot's experiment clock, then
    // advanced by wall time * time_scale with a gentle pull toward the
    // backend clock (so source phases stay aligned without ever jumping).
    let simT: number | null = null;
    let lastNow: number | null = null;

    let raf = 0;
    const draw = () => {
      raf = requestAnimationFrame(draw);
      const pair = pairRef.current;
      if (!pair) return;

      const now = performance.now();
      const state = interpolate(pair, now);
      const waves = state.objects.find(
        (o): o is WavesObject => o.type === "waves",
      );
      if (!waves) return;

      const backendT =
        waves.t + ((now - pair.currAt) / 1000) * waves.time_scale;
      if (simT === null || lastNow === null) {
        simT = backendT;
        lastNow = now;
        return;
      }
      const wallDt = Math.min(0.1, (now - lastNow) / 1000);
      lastNow = now;
      let advance = wallDt * waves.time_scale;
      advance += 0.05 * (backendT - simT - advance); // drift correction

      // c in cells/s; substeps sized to the CFL limit. A paused/negative
      // advance (drift pull) renders the existing field without stepping —
      // a dt of exactly 0 would still extrapolate (2u - u_prev) and blow up.
      const cCells = waves.c / GRID_PX;
      const dtMax = CFL / cCells;
      const n =
        advance > 1e-6
          ? Math.min(MAX_STEPS, Math.max(1, Math.ceil(advance / dtMax)))
          : 0;
      const dt = n > 0 ? advance / n : 0;

      const count = Math.min(6, waves.sources.length);
      for (let i = 0; i < count; i++) {
        const s = waves.sources[i];
        srcArr[i * 4] = s.x / GRID_PX;
        srcArr[i * 4 + 1] = s.y / GRID_PX;
        srcArr[i * 4 + 2] = s.freq;
        srcArr[i * 4 + 3] = s.born;
      }

      gl.useProgram(stepProg);
      gl.viewport(0, 0, simW, simH);
      gl.uniform1i(uField, 0);
      gl.uniform2f(uSim, simW, simH);
      gl.uniform1f(uS2, cCells * dt * (cCells * dt));
      gl.uniform1f(uDelta, Math.min(1, (2 * dt) / DECAY_TAU_S));
      gl.uniform1i(uCount, count);
      gl.uniform4fv(uSources, srcArr);
      gl.uniform1f(uAmp, count ? waves.sources[0].amp : 1);
      gl.uniform1f(uRamp, RAMP_S);
      gl.activeTexture(gl.TEXTURE0);
      for (let k = 0; k < n; k++) {
        simT += dt;
        gl.uniform1f(uTime, simT);
        gl.bindFramebuffer(gl.FRAMEBUFFER, next.fbo);
        gl.bindTexture(gl.TEXTURE_2D, curr.tex);
        gl.drawArrays(gl.TRIANGLES, 0, 3);
        [curr, next] = [next, curr];
      }

      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.useProgram(renderProg);
      gl.uniform1i(uRenderField, 0);
      gl.bindTexture(gl.TEXTURE_2D, curr.tex);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    };
    raf = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(raf);
      for (const f of [curr, next]) {
        gl.deleteTexture(f.tex);
        gl.deleteFramebuffer(f.fbo);
      }
      gl.deleteProgram(stepProg);
      gl.deleteProgram(renderProg);
      gl.deleteBuffer(vbo);
      gl.deleteVertexArray(vao);
    };
  }, [pairRef, simW, simH, frameW, frameH]);

  // Display resolution can stay at sim scale * 2 — the field is smooth, so
  // there is no point paying a 1080p fill rate for it; CSS upscales.
  return (
    <canvas
      ref={canvasRef}
      className="layer gl-layer"
      width={simW * 2}
      height={simH * 2}
    />
  );
}
