const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const origin = `http://127.0.0.1:${Number(process.argv[2] || 8938)}`;
const output = process.env.WU_OUTSIDE_EVIDENCE || "/tmp/wu-outside-family";
fs.mkdirSync(output, { recursive: true });
(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH || "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox"],
  });
  const results = [];
  for (const [width, height] of [
    [360, 800],
    [1440, 1000],
  ]) {
    const page = await browser.newPage({ viewport: { width, height } }),
      errors = [],
      writes = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.route("**/*", (route) => {
      const request = route.request();
      if (request.method() !== "GET")
        writes.push(request.method() + " " + request.url());
      return new URL(request.url()).origin === origin
        ? route.continue()
        : route.abort();
    });
    await page.goto(origin + "/roster-outside-preview.html");
    await page.getByRole("button", { name: "Filters", exact: true }).click();
    const panel = page.locator(".roster-filters-panel");
    await panel.waitFor();
    const status = panel
      .locator("fieldset")
      .filter({
        has: page.locator("legend").getByText("Status", { exact: true }),
      });
    const outside = status
      .locator("label")
      .filter({ hasText: "Outside family" });
    assert.equal(await outside.locator("small").innerText(), "13");
    assert.equal(await status.locator("input[type=checkbox]").count(), 6);
    const measure = await panel.evaluate((panel) => ({
      scroll: document.documentElement.scrollWidth,
      width: innerWidth,
      boxes: [
        ...panel.querySelectorAll(".roster-filters-options"),
      ][0].querySelectorAll("label").length,
      targets:
        [
          ...panel.querySelectorAll(".roster-filters-options"),
        ][0].querySelectorAll("label").length &&
        [
          ...[
            ...panel.querySelectorAll(".roster-filters-options"),
          ][0].querySelectorAll("label"),
        ].map((label) => ({
          height: label.getBoundingClientRect().height,
          left: label.getBoundingClientRect().left,
          right: label.getBoundingClientRect().right,
        })),
    }));
    assert(measure.scroll <= width, "No page overflow");
    assert(
      measure.targets.every(
        (box) => box.height >= 44 && box.left >= 0 && box.right <= width,
      ),
      "Status tiles fit with44px targets",
    );
    await page.screenshot({ path: path.join(output, `${width}-panel.png`) });
    await outside.locator("input").check();
    await page
      .getByRole("button", { name: "Show 13 accounts", exact: true })
      .click();
    await page.locator('[data-outside-results="13"]').waitFor();
    await page
      .getByRole("button", {
        name: "Remove Outside family filter",
        exact: true,
      })
      .waitFor();
    await page.screenshot({ path: path.join(output, `${width}-active.png`) });
    await page.getByRole("button", { name: "Clear all", exact: true }).click();
    await page.locator('[data-outside-results="65"]').waitFor();
    assert.equal(
      await page
        .getByRole("button", {
          name: "Remove Outside family filter",
          exact: true,
        })
        .count(),
      0,
    );
    assert.deepEqual(errors, []);
    assert.deepEqual(writes, []);
    results.push({ width, height, ...measure, writes: 0 });
    await page.close();
  }
  fs.writeFileSync(
    path.join(output, "measurements.json"),
    JSON.stringify(results, null, 2),
  );
  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
