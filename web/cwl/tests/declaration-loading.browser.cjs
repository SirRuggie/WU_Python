/* Read-only sample transport; no production API proxy or notification writes. */
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const port = Number(process.argv[2]);
assert(port > 1024 && port !== 8767);
const origin = `http://127.0.0.1:${port}`;
const out = path.resolve(__dirname, "../../../.local/loading-layout");
fs.mkdirSync(out, { recursive: true });
(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox"],
  });
  const results = [];
  try {
    for (const width of [320, 360, 390, 1440]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      const errors = [];
      page.on("pageerror", (e) => errors.push(e.message));
      await page.route("**/*", (route) =>
        new URL(route.request().url()).origin === origin
          ? route.continue()
          : route.abort(),
      );
      for (const state of ["pending", "unavailable"]) {
        await page.goto(
          `${origin}/declaration-extras-preview.html?locations=${state}`,
        );
        const label =
          state === "pending" ? "Checking locations…" : "Locations unavailable";
        const ping = page.getByRole("button", { name: label, exact: true });
        await ping.waitFor();
        assert(await ping.isDisabled());
        assert((await ping.boundingBox()).height >= 44);
        for (const box of await page
          .locator(".declaration-clan-toggle")
          .evaluateAll((nodes) =>
            nodes.map((n) => n.getBoundingClientRect().height),
          ))
          assert(box >= 44);
        const text = await page.locator(".arrival-check").innerText();
        assert(!text.includes("Ping 0 missing"));
        assert(!/0\/(15|30) in clan/.test(text));
        await page.screenshot({
          path: path.join(out, `${width}-${state}.png`),
          fullPage: true,
        });
        const layout = await page.evaluate(() => ({
          width: innerWidth,
          scroll: document.documentElement.scrollWidth,
        }));
        assert(layout.scroll <= width + 1, JSON.stringify(layout));
        assert(
          (await page.evaluate(() => window.declarationMethods())).every(
            (m) => m === "GET",
          ),
        );
        results.push({ width, state, ...layout });
      }
      await page.getByRole("button", { name: "Refresh", exact: true }).click();
      await page.getByRole("button", { name: /^Ping \d+ missing$/ }).waitFor();
      const loaded = await page.locator(".arrival-check").innerText();
      assert(!loaded.includes("Locations unavailable"));
      assert(/\d+\/(15|30) in clan/.test(loaded));
      const loadedLayout = await page.evaluate(() => ({
        width: innerWidth,
        scroll: document.documentElement.scrollWidth,
      }));
      assert(loadedLayout.scroll <= width + 1, JSON.stringify(loadedLayout));
      results.push({ width, state: "loaded", ...loadedLayout });
      await page.screenshot({
        path: path.join(out, `${width}-loaded.png`),
        fullPage: true,
      });
      assert(
        (await page.evaluate(() => window.declarationMethods())).every(
          (m) => m === "GET",
        ),
      );
      assert.deepEqual(errors, []);
      await page.close();
    }
  } finally {
    await browser.close();
  }
  fs.writeFileSync(
    path.join(out, "measurements.json"),
    JSON.stringify(results, null, 2),
  );
  console.log(JSON.stringify(results));
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
