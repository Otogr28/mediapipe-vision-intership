import { useEffect, useRef } from "react";
import { interpolate } from "../state/interp";
import type { SnapshotPair } from "../state/useAppState";
import type { ChargesObject } from "../state/types";
import fragSrc from "./charges.frag.glsl?raw";
import vertSrc from "./fullscreen.vert.glsl?raw";

interface Props {
  pairRef: React.RefObject<SnapshotPair | null>;
  frameW: number;
  frameH: number;
}

/** Mirrors config.CHG_MAX and the shader's u_charges array length. */
const MAX_CHARGES = 8;

/**
 * The electrostatic field layer: a transparent WebGL2 canvas that evaluates
 * V = k*sum(q/r) analytically per pixel and paints it as a diverging tint
 * plus equipotential bands.
 *
 * This is stateless — no ping-pong, no timestep — so it just re-evaluates
 * the closed form from the charge list every frame and needs no float
 * render target (unlike WavesLayer). Mount ONLY while a charges experiment
 * is active. Field LINES are drawn on top by the Canvas2D overlay.
 *
 * `?glscale=0.75` renders at reduced resolution and lets CSS upscale — the
 * Jetson escape hatch, same knob as the black hole.
 */
export function ChargesLayer({ pairRef, frameW, frameH }: Props) {
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
      console.error("WebGL2 unavailable — charges field disabled");
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
    const uCharges = u("u_charges");
    const uK = u("u_k");
    const uSoften = u("u_soften");
    const uEquipot = u("u_equipot_step");

    gl.viewport(0, 0, w, h);
    gl.uniform2f(uResolution, frameW, frameH);

    const arr = new Float32Array(MAX_CHARGES * 3);

    let raf = 0;
    const draw = () => {
      raf = requestAnimationFrame(draw);
      const pair = pairRef.current;
      if (!pair) return;
      const state = interpolate(pair, performance.now());
      const chg = state.objects.find(
        (o): o is ChargesObject => o.type === "charges",
      );
      if (!chg) return;

      const count = Math.min(MAX_CHARGES, chg.charges.length);
      for (let i = 0; i < count; i++) {
        const c = chg.charges[i];
        arr[i * 3] = c.x;
        arr[i * 3 + 1] = c.y;
        arr[i * 3 + 2] = c.q;
      }

      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      if (count === 0) return; // no charges -> fully transparent

      gl.uniform1i(uCount, count);
      gl.uniform3fv(uCharges, arr);
      gl.uniform1f(uK, chg.k);
      gl.uniform1f(uSoften, chg.soften);
      gl.uniform1f(uEquipot, chg.equipot_step);
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
