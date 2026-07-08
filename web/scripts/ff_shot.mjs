// Firefox screenshot harness (mirrors shot.mjs but drives Firefox via
// puppeteer BiDi) — to test whether three-vrm renders in the SAME engine the
// Jetson kiosk uses. Usage: node scripts/ff_shot.mjs [url] [out.png] [waitMs]
import puppeteer from "puppeteer-core";

const [url = "http://localhost:5173/", out = "ff.png", waitMs = "9000"] =
  process.argv.slice(2);

const browser = await puppeteer.launch({
  browser: "firefox",
  executablePath: "/usr/bin/firefox",
  headless: true,
  protocol: "webDriverBiDi",
});

const page = await browser.newPage();
await page.setViewport({ width: 1600, height: 900 });
const msgs = [];
page.on("console", (m) => {
  const t = m.text();
  if (t.includes("VRMDBG") || m.type() === "error" || m.type() === "warning")
    msgs.push(`${m.type()}: ${t}`);
});
page.on("pageerror", (e) => msgs.push(`pageerror: ${e.message}`));

await page.goto(url, { waitUntil: "load", timeout: 30000 });
await new Promise((r) => setTimeout(r, Number(waitMs)));

// Count non-transparent canvases (does the WebGL avatar canvas have content?)
const info = await page.evaluate(() => {
  const cs = [...document.querySelectorAll("canvas")].map((c) => ({
    w: c.width,
    h: c.height,
  }));
  return { canvases: cs.length, sizes: cs };
});

await page.screenshot({ path: out });
console.log(JSON.stringify(info));
console.log(msgs.length ? "CONSOLE:\n" + msgs.join("\n") : "no console errors");
console.log("saved " + out);
await browser.close();
