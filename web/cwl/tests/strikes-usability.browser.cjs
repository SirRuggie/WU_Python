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
          viewport: { width, height: width === 1440 ? 1000 : 800 },
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
            .locator(".strike-tab-predicate")
            .filter({ hasText: "No attacks in last 3+ known wars" })
            .count(),
        );
        if (count === 560 && [360, 1440].includes(width))
          await page.screenshot({
            path: path.join(output, `${width}-not-attacking.png`),
          });
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
          firstRowTop: document
            .querySelector(".strike-activity-entry")
            .getBoundingClientRect().top,
          row: document
            .querySelector(".strike-activity-entry")
            .getBoundingClientRect().height,
          rowsInViewport: [
            ...document.querySelectorAll(".strike-activity-entry"),
          ].filter((row) => {
            const r = row.getBoundingClientRect();
            return r.top >= 0 && r.bottom <= innerHeight;
          }).length,
          childrenFit: [
            ...document.querySelectorAll(".strike-activity-entry"),
          ].every((row) =>
            [...row.querySelectorAll("td")]
              .filter((cell) => getComputedStyle(cell).display !== "none")
              .every(
                (cell) =>
                  cell.getBoundingClientRect().bottom <=
                  row.getBoundingClientRect().bottom + 1,
              ),
          ),
          headings: [
            ...document.querySelectorAll(".strike-activity-table th"),
          ].map((node) => node.textContent.trim().replace(/ [↑↓]$/, "")),
        }));
        assert(metrics.scrollWidth <= width, JSON.stringify(metrics));
        assert(metrics.childrenFit, "Cell content overflows row geometry");
        assert(metrics.toolbar <= 60, JSON.stringify(metrics));
        assert(
          metrics.firstRowTop <= (width >= 1000 ? 200 : 360),
          JSON.stringify(metrics),
        );
        if (width >= 1000)
          assert(metrics.rowsInViewport >= 18, JSON.stringify(metrics));
        assert(metrics.row >= (width < 900 ? 80 : 44));
        assert(
          metrics.row <= (width < 900 ? 100 : 75),
          JSON.stringify(metrics),
        );
        assert.deepEqual(metrics.headings, [
          "Player",
          "TH",
          "Clan",
          "Weight",
          "Strikes",
          "Quiet",
          "Wars",
          "Raids",
          "Priority",
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
        await page.evaluate(() =>
          window.scrollTo(
            0,
            document
              .querySelector(".strike-activity-table tbody")
              .getBoundingClientRect().top +
              scrollY -
              (innerWidth >= 900 ? 89 : 54),
          ),
        );
        await page.waitForTimeout(80);
        const scrolled = await page.evaluate(() => ({
          toolbarTop: document
            .querySelector(".strike-activity-toolbar")
            .getBoundingClientRect().top,
          headerTop: document
            .querySelector(".strike-activity-table th")
            .getBoundingClientRect().top,
          rows: [...document.querySelectorAll(".strike-activity-entry")].filter(
            (row) => {
              const r = row.getBoundingClientRect();
              return (
                r.top >= (innerWidth >= 900 ? 88 : 54) &&
                r.bottom <= innerHeight
              );
            },
          ).length,
        }));
        assert(
          scrolled.toolbarTop >= -1 && scrolled.toolbarTop <= 1,
          JSON.stringify(scrolled),
        );
        if (width >= 900)
          assert(
            scrolled.headerTop >= 43 && scrolled.headerTop <= 46,
            JSON.stringify(scrolled),
          );
        if (count === 560)
          await page.screenshot({
            path: path.join(output, `${width}-560-scrolled.png`),
          });
        Object.assign(metrics, { scrolledRowsInViewport: scrolled.rows });
        await page.evaluate(() => window.scrollTo(0, 0));
        if (count === 560 && [360, 1440].includes(width)) {
          for (const [label, name] of [
            ["Inactive", "inactive"],
            ["Replacements", "replacements"],
          ]) {
            await page
              .getByRole("button", { name: new RegExp(`^${label} `) })
              .click();
            await page.screenshot({
              path: path.join(output, `${width}-${name}.png`),
            });
          }
        }
        assert.deepEqual(errors, []);
        evidence.push({ ...metrics, count });
        await page.unrouteAll({ behavior: "wait" });
        if (count === 560 && [360, 1440].includes(width)) {
          await page.evaluate(() =>
            window.scrollTo(0, document.body.scrollHeight),
          );
          await page.getByLabel("Activity actions").click();
          await page
            .getByRole("button", { name: "Find war", exact: true })
            .click();
          const search = page.getByPlaceholder("Opponent, clan, or date");
          await search.waitFor();
          assert(
            await search.evaluate((node) => node === document.activeElement),
          );
          const box = await search.boundingBox();
          assert(
            box.y >= 0 && box.y + box.height <= (width === 1440 ? 1000 : 800),
            JSON.stringify(box),
          );
          assert.equal(
            await page.locator(".strike-activity-actions").getAttribute("open"),
            null,
          );
          await page.screenshot({
            path: path.join(output, `${width}-find-war-focused.png`),
          });
        }
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
