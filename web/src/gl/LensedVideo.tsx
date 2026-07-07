import { useEffect, useRef } from "react";
import { interpolate } from "../state/interp";
import type { SnapshotPair } from "../state/useAppState";
import type { BlackHoleObject } from "../state/types";
import fragSrc from "./blackhole.frag.glsl?raw";
import vertSrc from "./fullscreen.vert.glsl?raw";

interface Props {
  pairRef: React.RefObject<SnapshotPair | null>;
  videoRef: React.RefObject<HTMLImageElement | null>;
  frameW: number;
  frameH: number;
}

/**
 * The black-hole layer: a WebGL2 canvas that samples the live MJPEG <img>
 * as a texture and runs the Schwarzschild lensing shader over it.
 *
 * Mount this ONLY while a black hole exists in the scene — unmounted, the
 * GPU does zero work and the plain <img> shows through. The canvas covers
 * the video layer completely while active (the shader passes the
 * background through outside the lensing region).
 *
 * `?glscale=0.75` (URL param) renders at reduced resolution and lets CSS
 * upscale — the Jetson escape hatch if 1080p drops frames.
 */
export function LensedVideo({ pairRef, videoRef, frameW, frameH }: Props) {
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
      alpha: false,
      premultipliedAlpha: false,
      antialias: false,
      preserveDrawingBuffer: false,
    });
    if (!gl) {
      console.error("WebGL2 unavailable — black hole disabled");
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

    // Fullscreen triangle.
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

    // Video texture. No UNPACK_FLIP_Y — the shader's uv is authored
    // top-left-origin to match both the upload orientation and OpenCV
    // pixel coordinates.
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.NONE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);

    const u = (name: string) => gl.getUniformLocation(program, name);
    const uFrame = u("u_frame");
    const uCenter = u("u_bh_center");
    const uEinstein = u("u_einstein_px");
    const uResolution = u("u_resolution");
    const uDiskInner = u("u_disk_inner_px");
    const uDiskOuter = u("u_disk_outer_px");
    const uDiskTilt = u("u_disk_tilt_rad");
    const uDiskBright = u("u_disk_brightness");
    const uTime = u("u_time");
    const uRotSpeed = u("u_rotation_speed");

    gl.viewport(0, 0, w, h);
    gl.uniform1i(uFrame, 0);
    gl.uniform2f(uResolution, w, h);

    let raf = 0;
    const draw = () => {
      raf = requestAnimationFrame(draw);
      const pair = pairRef.current;
      const img = videoRef.current;
      if (!pair || !img || img.naturalWidth === 0) return;

      const now = performance.now();
      const state = interpolate(pair, now);
      const bh = state.objects.find(
        (o): o is BlackHoleObject => o.type === "black_hole",
      );
      if (!bh) return;

      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, gl.RGBA, gl.UNSIGNED_BYTE, img);

      // Uniforms are in canvas pixels (glscale-adjusted).
      const s = glScale;
      gl.uniform2f(uCenter, bh.x * s, bh.y * s);
      gl.uniform1f(uEinstein, bh.einstein_px * s);
      gl.uniform1f(uDiskInner, bh.disk_inner_px * s);
      gl.uniform1f(uDiskOuter, bh.disk_outer_px * s);
      gl.uniform1f(uDiskTilt, bh.disk_tilt_rad);
      gl.uniform1f(uDiskBright, bh.disk_brightness);
      // Continuous rotation between 30 Hz snapshots: extrapolate the
      // backend disk clock by the local time since the snapshot arrived.
      gl.uniform1f(uTime, bh.disk_t + (now - pair.currAt) / 1000);
      gl.uniform1f(uRotSpeed, bh.rotation_speed);

      gl.drawArrays(gl.TRIANGLES, 0, 3);
    };
    raf = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(raf);
      gl.deleteTexture(tex);
      gl.deleteProgram(program);
      gl.deleteBuffer(vbo);
      gl.deleteVertexArray(vao);
    };
  }, [pairRef, videoRef, w, h, glScale]);

  return (
    <canvas
      ref={canvasRef}
      className="layer gl-layer"
      width={w}
      height={h}
    />
  );
}
