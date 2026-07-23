import { useEffect, useRef } from "react";
import { interpolate } from "../state/interp";
import type { SnapshotPair } from "../state/useAppState";
import type { MagnetsObject } from "../state/types";
import fragSrc from "./magnets.frag.glsl?raw";
import vertSrc from "./fullscreen.vert.glsl?raw";

interface Props {
  pairRef: React.RefObject<SnapshotPair | null>;
  frameW: number;
  frameH: number;
}

/** Mirrors config.MAG_MAX and the shader's u_magnets array length. */
const MAX_MAGNETS = 4;

/**
 * The magnetic field layer: a transparent WebGL2 canvas that evaluates the
 * bars' exact 2D field per needle cell and paints the iron-filings compass
 * grid. Stateless like ChargesLayer — no ping-pong, no timestep — so it
 * re-evaluates the closed form from the magnet list every frame. Mount ONLY
 * while a magnets experiment is active. The bars, coil, bulb and
 * galvanometer are drawn on top by the Canvas2D overlay.
 *
 * `?glscale=0.75` renders at reduced resolution and lets CSS upscale — the
 * Jetson escape hatch, same knob as the black hole.
 */
export function MagnetsLayer({ pairRef, frameW, frameH }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const glScale = (() => {
    const v = Number(new URLSearchParams(location.search).get("glscale"));
    return v > 0 && v <= 1 ? v : 1;
  })();
  const w = Math.round(frameW * glScale);
  const h = Math.round(frameH * glScale);

  useEffect(() => {
    const canvas = canvasRef.current!;
    const gl = canvas.getContext("webgl2", {
      alpha: true,
      antialias: false,
      preserveDrawingBuffer: false,
    });
    if (!gl) {
      console.error("WebGL2 unavailable — magnets field disabled");
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
    const program = gl.createProgram()!;
    gl.attachShader(program, compile(gl.VERTEX_SHADER, vertSrc));
    gl.attachShader(program, compile(gl.FRAGMENT_SHADER, fragSrc));
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      throw new Error(gl.getProgramInfoLog(program) ?? "program link failed");
    }
    gl.useProgram(program);

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

    const u = (name: string) => gl.getUniformLocation(program, name);
    const uResolution = u("u_resolution");
    const uCount = u("u_count");
    const uMagnets = u("u_magnets");
    const uHalfLen = u("u_half_len");
    const uHalfH = u("u_half_h");
    const uEdgeSmooth = u("u_edge_smooth");
    const uBRef = u("u_b_ref");
    const uSpacing = u("u_spacing");
    const uNeedleLen = u("u_needle_len");

    gl.viewport(0, 0, w, h);
    gl.uniform2f(uResolution, frameW, frameH);

    const arr = new Float32Array(MAX_MAGNETS * 3);

    let raf = 0;
    const draw = () => {
      raf = requestAnimationFrame(draw);
      const pair = pairRef.current;
      if (!pair) return;
      const state = interpolate(pair, performance.now());
      const mag = state.objects.find(
        (o): o is MagnetsObject => o.type === "magnets",
      );
      if (!mag) return;

      const count = Math.min(MAX_MAGNETS, mag.magnets.length);
      for (let i = 0; i < count; i++) {
        const m = mag.magnets[i];
        arr[i * 3] = m.x;
        arr[i * 3 + 1] = m.y;
        arr[i * 3 + 2] = m.m;
      }

      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      if (count === 0) return; // no magnets -> fully transparent

      gl.uniform1i(uCount, count);
      gl.uniform3fv(uMagnets, arr);
      gl.uniform1f(uHalfLen, mag.half_len);
      gl.uniform1f(uHalfH, mag.half_h);
      gl.uniform1f(uEdgeSmooth, mag.edge_smooth);
      gl.uniform1f(uBRef, mag.b_ref);
      gl.uniform1f(uSpacing, mag.needle_spacing);
      gl.uniform1f(uNeedleLen, mag.needle_len);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    };
    raf = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(raf);
      gl.deleteProgram(program);
      gl.deleteBuffer(vbo);
      gl.deleteVertexArray(vao);
    };
  }, [pairRef, w, h, frameW, frameH]);

  return <canvas ref={canvasRef} className="layer gl-layer" width={w} height={h} />;
}
