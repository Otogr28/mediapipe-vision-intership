// Dev verification harness: open the frontend in headless Chrome, report
// console errors + stream/SSE health, and save a screenshot.
//
// Usage: node scripts/shot.mjs [url] [out.png] [waitMs]
// (defaults: the vite dev server, shot.png, 4000)
import puppeteer from "puppeteer-core";

const [url = "http://localhost:5173/", out = "shot.png", waitMs = "4000"] =
  process.argv.slice(2);

const browser = await puppeteer.launch({
  executablePath:
    process.env.CHROME_BIN ?? "/usr/bin/google-chrome-stable",
  headless: true,
  // --enable-unsafe-swiftshader: headless Chrome dropped automatic
  // software-WebGL fallback; without it the GL context is created but
  // immediately lost (CONTEXT_LOST_WEBGL) and the black-hole layer
  // renders nothing. Harmless for real GPUs.
  args: [
    "--no-sandbox",
    "--window-size=1600,900",
    "--enable-unsafe-swiftshader",
  ],
  defaultViewport: { width: 1600, height: 900 },
});

const page = await browser.newPage();
const errors = [];
page.on("console", (msg) => {
  if (msg.type() === "error" || msg.type() === "warning")
    errors.push(`[${msg.type()}] ${msg.text()}`);
});
page.on("pageerror", (err) => errors.push(`[pageerror] ${err.message}`));

await page.goto(url, { waitUntil: "domcontentloaded", timeout: 15000 });
await new Promise((r) => setTimeout(r, Number(waitMs)));

const info = await page.evaluate(() => {
  const img = document.querySelector("img.layer");
  const canvas = document.querySelector("canvas.layer");
  return {
    imgNatural: img ? `${img.naturalWidth}x${img.naturalHeight}` : "no img",
    imgComplete: img?.complete ?? null,
    canvasSize: canvas ? `${canvas.width}x${canvas.height}` : "no canvas",
    banner: !!document.querySelector(".conn-banner"),
    buttons: [...document.querySelectorAll("[data-btn-id]")].map((b) =>
      b.getAttribute("data-btn-id"),
    ),
    glCanvas: !!document.querySelector("canvas.gl-layer"),
  };
});
console.log(JSON.stringify(info, null, 1));
console.log(
  errors.length ? "CONSOLE:\n" + errors.join("\n") : "no console errors",
);

await page.screenshot({ path: out });
console.log("saved", out);
await browser.close();
