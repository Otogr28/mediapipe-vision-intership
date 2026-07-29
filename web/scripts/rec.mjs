// Dev capture harness: record a short clip of the frontend running against
// `mock_backend.py`, for the looping demo animations on the docs site.
//
// Same headless Chrome as shot.mjs, but instead of one screenshot it drives
// CDP `Page.startScreencast`, which delivers a JPEG whenever the page paints.
// Frames arrive at a variable rate, so their CDP timestamps are written into
// an ffmpeg concat list — the encoder resamples from real timing instead of
// guessing a frame rate.
//
// Usage: node scripts/rec.mjs <url> <outDir> [recordMs] [warmupMs] [w] [h]
//
// The docs-site demo clips (docs/img/<scene>.mp4) were made from this, one mock
// scene at a time, with the poster still taken from the clip's own first frame:
//
//   HALL_MOCK_BG=carina.jpg HALL_MOCK_LABEL=0 \
//     uv run python web/scripts/mock_backend.py waves      # then, in web/:
//   node scripts/rec.mjs http://localhost:5173/ /tmp/rec_waves 7000 7000
//   cd /tmp/rec_waves && ffmpeg -f concat -safe 0 -i list.txt \
//     -vf "fps=12,scale=800:450:flags=lanczos,setsar=1" -c:v libx264 -crf 30 \
//     -preset slow -pix_fmt yuv420p -movflags +faststart -an waves.mp4
//   ffmpeg -i f00000.jpg -qscale:v 4 waves.jpg
//
// setsar=1 is load-bearing: Chrome's screencast JPEGs carry a JFIF pixel
// density that makes ffmpeg stamp a 300:271 aspect on the stream, and the
// browser then renders the clip 886x450 inside its 16:9 box.
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import puppeteer from "puppeteer-core";

const [
  url = "http://localhost:5173/",
  outDir = "rec",
  recordMs = "6000",
  warmupMs = "6000",
  w = "1600",
  h = "900",
] = process.argv.slice(2);

const width = Number(w);
const height = Number(h);

rmSync(outDir, { recursive: true, force: true });
mkdirSync(outDir, { recursive: true });

const browser = await puppeteer.launch({
  executablePath: process.env.CHROME_BIN ?? "/usr/bin/google-chrome-stable",
  headless: true,
  // --enable-unsafe-swiftshader: see shot.mjs — without it the WebGL layers
  // (black hole, waves, charges, magnets) come back blank in headless.
  args: [
    "--no-sandbox",
    `--window-size=${width},${height}`,
    "--enable-unsafe-swiftshader",
    "--hide-scrollbars",
  ],
  defaultViewport: { width, height },
});

const page = await browser.newPage();
const errors = [];
page.on("console", (m) => {
  if (m.type() === "error") errors.push(`[error] ${m.text()}`);
});
page.on("pageerror", (e) => errors.push(`[pageerror] ${e.message}`));

await page.goto(url, { waitUntil: "domcontentloaded", timeout: 20000 });
await new Promise((r) => setTimeout(r, Number(warmupMs)));

const client = await page.createCDPSession();
await client.send("Page.enable");

const frames = [];
client.on("Page.screencastFrame", async ({ data, sessionId, metadata }) => {
  const name = `f${String(frames.length).padStart(5, "0")}.jpg`;
  writeFileSync(join(outDir, name), Buffer.from(data, "base64"));
  frames.push({ name, t: metadata.timestamp });
  try {
    await client.send("Page.screencastFrameAck", { sessionId });
  } catch {
    /* screencast already stopped */
  }
});

await client.send("Page.startScreencast", {
  format: "jpeg",
  quality: 95,
  maxWidth: width,
  maxHeight: height,
  everyNthFrame: 1,
});
await new Promise((r) => setTimeout(r, Number(recordMs)));
await client.send("Page.stopScreencast");

// ffmpeg concat list: each frame lasts until the next one arrived. The last
// frame has no successor, so it gets the median duration and is repeated —
// the concat demuxer ignores the duration of the final entry.
const gaps = frames.slice(1).map((f, i) => f.t - frames[i].t);
const sorted = [...gaps].sort((a, b) => a - b);
const median = sorted.length ? sorted[Math.floor(sorted.length / 2)] : 1 / 15;
const lines = frames.map((f, i) => {
  const d = i + 1 < frames.length ? frames[i + 1].t - f.t : median;
  return `file '${f.name}'\nduration ${Math.max(d, 1 / 240).toFixed(4)}`;
});
if (frames.length) lines.push(`file '${frames.at(-1).name}'`);
writeFileSync(join(outDir, "list.txt"), lines.join("\n") + "\n");

const span = frames.length > 1 ? frames.at(-1).t - frames[0].t : 0;
console.log(
  JSON.stringify({
    frames: frames.length,
    seconds: Number(span.toFixed(2)),
    fps: span ? Number(((frames.length - 1) / span).toFixed(1)) : 0,
    errors,
  }),
);

await browser.close();
