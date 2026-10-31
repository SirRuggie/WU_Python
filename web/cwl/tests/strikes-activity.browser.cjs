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
          firstRowY:
            document
              .querySelector(".strike-activity-row")
              ?.getBoundingClientRect().top ?? null,
          small: [
            ...document.querySelectorAll(
              ".strike-activity-roster button,.strike-activity-roster select,.strike-activity-roster input:not([type=checkbox]),.strike-activity-roster summary,.strike-review-resolution button,.strike-review-resolution textarea,.confirm-dialog button",
            ),
          ]
            .filter(
              (e) =>
                e.checkVisibility() && e.getBoundingClientRect().height < 44,
            )
            .map((e) => e.textContent),
          text: [
            ...document.querySelectorAll(
              ".strike-activity-roster *, .strike-review-resolution *, .confirm-dialog *",
            ),
          ]
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
        if (name === "default" && (width === 360 || width === 1440))
          assert(
            measure.firstRowY <= (width === 360 ? 420 : 360),
            `first player at ${measure.firstRowY}`,
          );
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
            fullPage: name === "all-chips" || name === "review",
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
      if (
        count === 125 &&
        ((width === 360 && height === 800) || width === 1440)
      ) {
        await page.goto(`${origin}/strikes-preview.html?count=125&review=1`);
        await page
          .getByRole("button", { name: "Find war", exact: true })
          .click();
        await page
          .getByRole("button", { name: /Unfinalized opponent/ })
          .click();
        await page
          .getByRole("heading", { name: "Staff review required" })
          .waitFor();
        await page
          .getByRole("button", { name: "Resolve review", exact: true })
          .click();
        await page
          .getByRole("textbox", { name: "Review reason" })
          .fill("Fixture staff reviewed missing final");
        await snap("review");
        await page
          .getByRole("button", {
            name: "Resolve and release hold",
            exact: true,
          })
          .click();
        await page.getByRole("dialog").waitFor();
        await snap("review-confirm");
        await page
          .getByRole("dialog")
          .getByRole("button", { name: "Resolve review", exact: true })
          .click();
        await page
          .getByText("War review resolved. The streak hold is released.", {
            exact: true,
          })
          .waitFor();
      }
      assert.equal(errors.length, 0, errors.join("\n"));
      await page.close();
    }
  for (const width of [360, 1440])
    for (const scope of ["add", "manage"]) {
      const page = await browser.newPage({
        viewport: { width, height: width === 360 ? 800 : 1000 },
      });
      await page.route("**/*", (route) =>
        new URL(route.request().url()).origin === origin
          ? route.continue()
          : route.abort(),
      );
      await page.goto(`${origin}/strikes-preview.html?count=26&scope=${scope}`);
      await page.locator(".strike-activity-row").first().waitFor();
      await page.getByLabel("Activity actions").click();
      if (scope === "add")
        assert.equal(
          await page
            .getByRole("button", { name: "Select accounts", exact: true })
            .count(),
          0,
        );
      else {
        await page
          .getByRole("button", { name: "Select accounts", exact: true })
          .click();
        assert.equal(
          await page
            .locator(".strike-activity-actions")
            .evaluate((el) => el.open),
          false,
        );
        await page
          .getByRole("button", { name: "Select all (26)", exact: true })
          .click();
        await page.getByText(/26 selected/).waitFor();
        assert.equal(
          await page.locator('[aria-label="Selected accounts"] li').count(),
          26,
          "Confirmation must list every account including the next page",
        );
        assert.equal(
          await page.locator('input[aria-label^="Select "]:checked').count(),
          25,
        );
        await page
          .getByRole("textbox", { name: "Note", exact: true })
          .fill("Fixture note — verify before marking");
        assert(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= innerWidth,
          ),
        );
        await page.screenshot({
          path: path.join(output, `${width}-bulk-selection.png`),
        });
        await page
          .getByRole("button", { name: "Next accounts", exact: true })
          .click();
        await page.waitForFunction(
          () => document.querySelectorAll(".strike-activity-row").length === 1,
        );
        assert.equal(
          await page.locator('input[aria-label^="Select "]:checked').count(),
          1,
        );
        await page.getByText(/26 selected/).waitFor();
        assert.equal(
          await page.locator('[aria-label="Selected accounts"] li').count(),
          26,
          "Confirmation must list every account including the next page",
        );
        await page
          .getByRole("button", { name: "Cancel selection", exact: true })
          .click();
      }
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
