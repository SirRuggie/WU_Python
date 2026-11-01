const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const port = Number(process.argv[2]);
assert(port > 1024 && port !== 8767);
const origin = `http://127.0.0.1:${port}`;
const out = path.resolve(__dirname, "../../../.local/filler-layout");
fs.mkdirSync(out, { recursive: true });
(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox"],
  });
  const results = [];
  try {
    for (const count of [26, 65, 125])
      for (const width of [320, 360, 390, 1440]) {
        const page = await browser.newPage({
          viewport: { width, height: 900 },
        });
        const errors = [];
        page.on("pageerror", (e) => errors.push(e.message));
        await page.route("**/*", (r) =>
          new URL(r.request().url()).origin === origin
            ? r.continue()
            : r.abort(),
        );
        await page.goto(`${origin}/roster-filler-preview.html?count=${count}`);
        await page
          .getByRole("heading", { name: `${count} accounts`, exact: true })
          .waitFor();
        assert.equal(
          await page
            .locator(".roster-account-card,.roster-player-card")
            .count(),
          count,
        );
        assert.equal(
          await page.locator(".roster-clan-chip.is-over").count(),
          0,
        );
        assert(
          (await page.locator(".roster-clan-chips").innerText()).includes(
            "+1 filler",
          ),
        );
        await page.screenshot({
          path: path.join(out, `${count}-${width}-overview.png`),
          fullPage: true,
        });
        await page
          .getByRole("button", { name: /Details for Sample member 1 with/ })
          .click();
        const mark = page.getByRole("checkbox", {
          name: /Filler: Sample member 1 with/,
        });
        await mark.waitFor();
        assert(await mark.isChecked());
        const target = await mark.locator("..").boundingBox();
        assert(target.height >= 44);
        await page.screenshot({
          path: path.join(out, `${count}-${width}-details.png`),
          fullPage: true,
        });
        await mark.uncheck();
        await page.waitForFunction(() => window.fillerFixture().revision === 2);
        assert(!(await mark.isChecked()));
        await page
          .getByRole("button", { name: "‹ Build roster", exact: true })
          .click();
        assert.equal(
          await page.locator(".roster-clan-chip.is-over").count(),
          1,
        );
        await page.locator(".declaration-low-th summary").click();
        const low = page.getByRole("checkbox", {
          name: "Filler: Low TH sample",
          exact: true,
        });
        await low.click();
        await page.waitForFunction(() => window.fillerFixture().revision === 3);
        assert.equal(await page.locator(".declaration-low-th").count(), 0);
        await page.locator(".declaration-extras summary").click();
        const dm = page
          .locator(".declaration-extras")
          .getByRole("link", { name: /DM/ });
        await dm.waitFor();
        assert((await dm.getAttribute("href")).includes("123456789012345678"));
        assert((await dm.boundingBox()).height >= 44);
        assert(
          !(await page.locator(".declaration-extras").innerText()).includes(
            "123456789012345678",
          ),
        );
        await page.screenshot({
          path: path.join(out, `${count}-${width}-dm.png`),
          fullPage: true,
        });
        const extra = page.getByRole("checkbox", {
          name: "Filler: Unexpected sample",
          exact: true,
        });
        await extra.click();
        await page.waitForFunction(() => window.fillerFixture().revision === 4);
        assert.equal(await page.locator(".declaration-extras").count(), 0);
        await page.locator(".declaration-fillers summary").click();
        await page.screenshot({
          path: path.join(out, `${count}-${width}-marked.png`),
          fullPage: true,
        });
        const metrics = await page.evaluate(() => ({
          scroll: document.documentElement.scrollWidth,
          width: innerWidth,
          ...window.fillerFixture(),
        }));
        assert(metrics.scroll <= width + 1, JSON.stringify(metrics));
        assert.deepEqual(
          metrics.methods.filter((m) => m !== "GET"),
          ["PATCH", "PATCH", "PATCH"],
        );
        assert.deepEqual(errors, []);
        results.push({
          width,
          count,
          scroll: metrics.scroll,
          fixtureWrites: metrics.methods.filter((m) => m !== "GET").length,
        });
        await page.close();
      }
  } finally {
    await browser.close();
    fs.writeFileSync(
      path.join(out, "results.json"),
      JSON.stringify(results, null, 2),
    );
  }
  console.log(JSON.stringify(results));
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
