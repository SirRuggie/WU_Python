const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const origin = "http://127.0.0.1:44792";
const out = path.resolve(__dirname, "../../../.local/p92-layout");
fs.mkdirSync(out, { recursive: true });
(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox"],
  });
  const results = [];
  try {
    for (const state of ["blank", "pending", "failure", "scan", "outage"])
      for (const width of [320, 360, 390, 1440]) {
        const page = await browser.newPage({
          viewport: { width, height: 1000 },
        });
        const errors = [];
        page.on("pageerror", (e) => errors.push(e.message));
        await page.route("**/*", (r) =>
          new URL(r.request().url()).origin === origin
            ? r.continue()
            : r.abort(),
        );
        await page.goto(`${origin}/pool-roles-preview.html?state=${state}`);
        await page.locator(".cwl-pool-role").first().waitFor();
        assert.equal(await page.locator(".cwl-pool-role").count(), 2);
        assert.deepEqual(errors, []);
        assert(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= innerWidth,
          ),
          `${state}/${width} overflow`,
        );
        const targets = await page
          .locator(
            ".cwl-pool-roles button,.cwl-pool-roles input,.cwl-pool-roles select",
          )
          .evaluateAll((nodes) =>
            nodes
              .filter((x) => x.getBoundingClientRect().height > 0)
              .map((x) => ({
                text: x.textContent,
                height: x.getBoundingClientRect().height,
              })),
          );
        assert(
          targets.every((x) => x.height >= 43.5),
          JSON.stringify(targets),
        );
        assert(
          (await page.evaluate(() => window.fixtureMethods)).every((x) =>
            x.startsWith("GET "),
          ),
        );
        await page.screenshot({
          path: path.join(out, `${state}-${width}.png`),
          fullPage: true,
        });
        results.push({ state, width, targets: targets.length });
        await page.close();
      }
    fs.writeFileSync(
      path.join(out, "results.json"),
      JSON.stringify(results, null, 2),
    );
    console.log(results.length + " role layouts pass");
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
