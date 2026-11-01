/* Own browser-only StrikesPreview transport; no production or live writes. */
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const origin = `http://127.0.0.1:${Number(process.argv[2])}`;
const output =
  process.env.WU_STRIKES_LAYOUT_OUTPUT || "/tmp/wu-strikes-usability";
fs.mkdirSync(output, { recursive: true });
(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    args: ["--no-sandbox"],
  });
  const evidence = [];
  try {
    for (const width of [320, 360, 390, 1440])
      for (const count of [26, 65, 125, 560]) {
        const context = await browser.newContext({
          viewport: { width, height: 900 },
          permissions: ["clipboard-read", "clipboard-write"],
        });
        const page = await context.newPage();
        const errors = [];
        page.on("pageerror", (error) => errors.push(error.message));
        await page.route("**/*", (route) =>
          new URL(route.request().url()).origin === origin
            ? route.continue()
            : route.abort(),
        );
        await page.goto(`${origin}/strikes-preview.html?count=${count}`);
        await page.locator("[data-strike-player]").first().waitFor();
        assert.equal(
          await page
            .getByRole("button", { name: /^Not attacking/ })
            .getAttribute("aria-pressed"),
          "true",
        );
        assert(
          await page
            .getByRole("button", {
              name: "Remove No attacks in last 3+ known wars",
            })
            .count(),
        );
        await page
          .getByRole("button", { name: new RegExp(`^All ${count}$`) })
          .click();
        assert.equal(await page.locator("[data-strike-player]").count(), 25);
        const metrics = await page.evaluate(() => ({
          width: innerWidth,
          scrollWidth: document.documentElement.scrollWidth,
          toolbar: document
            .querySelector(".strike-activity-toolbar")
            .getBoundingClientRect().height,
          row: document
            .querySelector(".strike-activity-entry")
            .getBoundingClientRect().height,
          rowsInViewport: [
            ...document.querySelectorAll(".strike-activity-entry"),
          ].filter((row) => {
            const r = row.getBoundingClientRect();
            return r.top >= 0 && r.bottom <= innerHeight;
          }).length,
          headings: [
            ...document.querySelectorAll(".strike-activity-table th"),
          ].map((node) => node.textContent),
        }));
        assert(metrics.scrollWidth <= width, JSON.stringify(metrics));
        assert(metrics.toolbar <= 60, JSON.stringify(metrics));
        assert(metrics.row >= 44);
        assert(
          metrics.row <= (width < 900 ? 100 : 75),
          JSON.stringify(metrics),
        );
        assert.deepEqual(metrics.headings, [
          "Account",
          "TH",
          "Clan",
          "Weight",
          "Strikes",
          "Activity",
        ]);
        await page
          .getByRole("button", { name: "Filters", exact: true })
          .click();
        await page.getByRole("dialog").waitFor();
        await page
          .getByRole("searchbox", { name: "Find clan", exact: true })
          .fill("North");
        assert.equal(
          await page
            .getByRole("dialog")
            .getByText("WU North", { exact: true })
            .count(),
          1,
        );
        await page
          .getByRole("button", { name: "Close panel", exact: true })
          .click();
        await page.waitForFunction(
          () => !document.querySelector("dialog[open]"),
        );
        await page.screenshot({
          path: path.join(output, `${width}-${count}.png`),
        });
        assert.deepEqual(errors, []);
        evidence.push({ ...metrics, count });
        await page.unrouteAll({ behavior: "wait" });
        await context.close();
      }
    fs.writeFileSync(
      path.join(output, "measurements.json"),
      JSON.stringify(evidence, null, 2),
    );
    console.log(JSON.stringify(evidence));
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
