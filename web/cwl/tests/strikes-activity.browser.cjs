const { chromium } = require("playwright");
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const origin = `http://127.0.0.1:${Number(process.argv[2])}`;
const output =
  process.env.WU_ACTIVITY_LAYOUT_OUTPUT || "/tmp/wu-activity-layout";
fs.mkdirSync(output, { recursive: true });
(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH || "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox"],
  });
  const measurements = [];
  for (const count of [26, 65, 125])
    for (const [width, height] of [
      [320, 800],
      [360, 800],
      [390, 800],
      [360, 500],
      [1440, 1000],
    ]) {
      const page = await browser.newPage({ viewport: { width, height } }),
        errors = [];
      page.on("pageerror", (e) => errors.push(e.message));
      await page.route("**/*", (r) =>
        new URL(r.request().url()).origin === origin ? r.continue() : r.abort(),
      );
      async function snap(name) {
        const measure = await page.evaluate(() => ({
          scroll: document.documentElement.scrollWidth,
          width: innerWidth,
          rows: document.querySelectorAll(".strike-activity-row").length,
          small: [
            ...document.querySelectorAll(
              ".strike-activity-roster button,.strike-activity-roster select,.strike-activity-roster input:not([type=checkbox]),.strike-activity-roster summary",
            ),
          ]
            .filter(
              (e) =>
                e.checkVisibility() && e.getBoundingClientRect().height < 44,
            )
            .map((e) => e.textContent),
          text: [...document.querySelectorAll(".strike-activity-roster *")]
            .filter(
              (e) =>
                e.checkVisibility() &&
                [...e.childNodes].some(
                  (n) => n.nodeType === 3 && n.textContent.trim(),
                ),
            )
            .map((e) => parseFloat(getComputedStyle(e).fontSize)),
          rowsAligned: [
            ...document.querySelectorAll(".strike-activity-row"),
          ].every((row) => {
            const name = row
                .querySelector(".strike-activity-identity")
                .getBoundingClientRect(),
              strike = row
                .querySelector(".strike-activity-count")
                .getBoundingClientRect();
            return Math.abs(name.top - strike.top) < 10;
          }),
        }));
        assert(measure.scroll <= width, "horizontal overflow");
        assert.equal(measure.small.length, 0, "44px target");
        assert(
          measure.text.every((size) => size >= 12),
          "12px text",
        );
        assert(measure.rowsAligned, "strike count stays beside identity");
        measurements.push({ count, width, name, ...measure });
        if (count === 125 && (height === 800 || width === 1440))
          await page.screenshot({
            path: path.join(output, `${width}-${name}.png`),
            fullPage: name === "all-chips",
          });
      }
      await page.goto(`${origin}/strikes-preview.html?count=${count}`);
      await page.locator(".strike-activity-row").first().waitFor();
      assert.equal(await page.locator(".strike-activity-row").count(), 25);
      await snap("default");
      const clan = page.locator(".strike-activity-clans");
      await clan.locator("summary").click();
      await clan.getByLabel("WU North", { exact: true }).check();
      await clan.locator("summary").click();
      await snap("filtered-clan");
      assert(new URL(page.url()).searchParams.get("clans").includes("#PYY"));
      await page.goto(
        `${origin}/strikes-preview.html?count=${count}&page=replacements`,
      );
      await page.locator(".strike-activity-row").first().waitFor();
      assert(
        await page
          .getByLabel("Marked for replacement", { exact: true })
          .isChecked(),
      );
      assert.equal(
        await page
          .locator(".strike-activity-count")
          .allTextContents()
          .then((rows) => rows.some((row) => /^0 /.test(row.trim()))),
        false,
      );
      await snap("replacements");
      await page
        .getByLabel("Marked for replacement", { exact: true })
        .uncheck();
      await page.getByRole("searchbox").fill("CastleFox");
      await snap("all-chips");
      assert(
        (await page.locator(".strike-activity-chip").allTextContents()).some(
          (text) => text.includes("Quiet for 48 days"),
        ),
      );
      await page.getByRole("searchbox").fill("Healthy Birch");
      await snap("healthy");
      assert.deepEqual(
        await page.locator(".strike-activity-chip").allTextContents(),
        ["Active today"],
      );
      await page.getByRole("searchbox").fill("New tracker Aspen");
      assert(
        (await page.locator(".strike-activity-chips").innerText()).includes(
          "Not seen since tracking began",
        ),
      );
      assert(
        !(await page.locator(".strike-activity-chips").innerText()).includes(
          "Quiet",
        ),
      );
      assert.equal(errors.length, 0, errors.join("\n"));
      await page.close();
    }
  fs.writeFileSync(
    path.join(output, "measurements.json"),
    JSON.stringify(measurements, null, 2),
  );
  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
