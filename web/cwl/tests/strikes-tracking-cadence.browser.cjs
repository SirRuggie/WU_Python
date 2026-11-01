/* Browser-only fixture: records its fake tracking reads, never production. */
const { chromium } = require("playwright");
const fs = require("node:fs");
const assert = require("node:assert/strict");
const origin = `http://127.0.0.1:${Number(process.argv[2])}`;
(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    args: ["--no-sandbox"],
  });
  try {
    const page = await browser.newPage();
    await page.route("**/*", (r) =>
      new URL(r.request().url()).origin === origin ? r.continue() : r.abort(),
    );
    await page.goto(origin + "/strikes-preview.html?count=26");
    await page.locator("[data-strike-player]").first().waitFor();
    await page.evaluate(() => {
      const fetch = window.fetch.bind(window);
      window.__trackingReads = [];
      const start = performance.now();
      window.fetch = (input, init) => {
        if (
          String(input).includes("/strikes/tracking") &&
          (init?.method || "GET") === "GET"
        )
          window.__trackingReads.push(performance.now() - start);
        return fetch(input, init);
      };
      for (let i = 0; i < 20; i++) window.dispatchEvent(new Event("focus"));
    });
    await page.waitForTimeout(65000);
    const visible = await page.evaluate(() => window.__trackingReads.slice());
    assert.equal(visible.length, 2, JSON.stringify(visible));
    assert(visible[1] - visible[0] >= 29000);
    await page.evaluate(() => {
      Object.defineProperty(document, "visibilityState", {
        configurable: true,
        value: "hidden",
      });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await page.waitForTimeout(35000);
    assert.equal(await page.evaluate(() => window.__trackingReads.length), 2);
    await page.evaluate(() => {
      Object.defineProperty(document, "visibilityState", {
        configurable: true,
        value: "visible",
      });
      document.dispatchEvent(new Event("visibilitychange"));
      for (let i = 0; i < 20; i++) window.dispatchEvent(new Event("focus"));
    });
    await page.waitForTimeout(1000);
    const reads = await page.evaluate(() => window.__trackingReads);
    assert.equal(reads.length, 3, JSON.stringify(reads));
    fs.writeFileSync(
      "/tmp/p65-tracking-browser-cadence.json",
      JSON.stringify(
        { visible, reads, hiddenSeconds: 35, focusBursts: 40 },
        null,
        2,
      ),
    );
    console.log(JSON.stringify(reads));
    await page.unrouteAll({ behavior: "wait" });
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
