import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev proxy: the backend (HALL_OUTPUT=web) serves the camera stream and the
// state SSE on :8092. Keeping them same-origin is REQUIRED — a cross-origin
// <img> taints the WebGL canvas and the black-hole shader throws a
// SecurityError on texImage2D. Point HALL_BACKEND at a remote backend
// (e.g. the Jetson over Tailscale) to develop against it.
const backend = process.env.HALL_BACKEND ?? "http://127.0.0.1:8092";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/state": backend,
      "/stream.mjpg": backend,
      "/stream": backend,
      "/snapshot.jpg": backend,
      "/healthz": backend,
      "/attract": backend,
    },
  },
});
