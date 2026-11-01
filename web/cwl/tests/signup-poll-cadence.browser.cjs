/* Optional90s real-Chrome cadence regression against an isolated player fixture. */
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const { performance } = require("node:perf_hooks");
const port = Number(process.argv[2]);
assert(port >= 8900 && port <= 8999);
const origin = `http://127.0.0.1:${port}`;
(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox"],
  });
  try {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 1000 },
    });
    const reads = [],
      writes = [],
      errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (url.origin !== origin) return;
      if (url.pathname === "/api/cwl/seasons/1/signup-activity")
        reads.push(performance.now());
      if (
        !["GET", "HEAD"].includes(request.method()) &&
        !url.pathname.endsWith("/dev/login")
      )
        writes.push(url.pathname);
    });
    await page.route("**/*", (route) =>
      new URL(route.request().url()).origin === origin
        ? route.continue()
        : route.abort(),
    );
    await page.goto(origin + "/cwl/roster?season=1");
    await page.getByRole("button", { name: "Open local test session" }).click();
    await page.locator(".roster-player-card").first().waitFor();
    await page.evaluate(() => {
      window.__visibilityTest = setInterval(
        () => document.dispatchEvent(new Event("visibilitychange")),
        100,
      );
    });
    await page.waitForTimeout(93000);
    const seconds = reads.map((value) => (value - reads[0]) / 1000);
    const gaps = seconds.slice(1).map((value, index) => value - seconds[index]);
    const result = {
      seconds,
      gaps,
      visible: await page.evaluate(() => !document.hidden),
      writes,
      errors,
    };
    fs.writeFileSync(
      process.env.WU_CADENCE_OUTPUT || "/tmp/p63-real-chrome-cadence.json",
      JSON.stringify(result, null, 2),
    );
    console.log(JSON.stringify(result));
    assert.equal(reads.length, 4);
    assert(
      gaps.every((value) => value > 26 && value < 36),
      "Expected approximately30s cadence without skipped alternate ticks",
    );
    assert.deepEqual(writes, []);
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
