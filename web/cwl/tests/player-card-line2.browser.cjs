/* Run against the isolated 125-account fixture, never production:
 * NODE_PATH=/path/to/playwright/node_modules node tests/player-card-line2.browser.cjs 8949
 * The fixture must include locked Lazy #QG02CY8LG in #J2Y. No data writes except dev login.
 */
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const port = Number(process.argv[2] || 8949);
assert(Number.isInteger(port) && port >= 8900 && port <= 8999);

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH || "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox"],
  });
  const results = [];
  try {
    for (const width of [320, 360, 700, 701, 1440]) {
      const page = await browser.newPage({
        viewport: { width, height: width >= 1000 ? 1000 : 800 },
      });
      await page.route("**/*", (route) =>
        new URL(route.request().url()).origin === `http://127.0.0.1:${port}`
          ? route.continue()
          : route.abort(),
      );
      await page.goto(`http://127.0.0.1:${port}/cwl/roster?season=1`);
      await page
        .getByRole("button", { name: "Open local test session" })
        .click();
      await page.locator(".roster-player-card").first().waitFor();
      await page
        .getByPlaceholder("Name, player tag or Discord ID")
        .fill("#QG02CY8LG");
      for (const mode of ["accounts", "compare"]) {
        if (mode === "compare") {
          await page.evaluate(() =>
            localStorage.setItem(
              "wu-compare-clans:1:lazy",
              JSON.stringify(["#J2Y"]),
            ),
          );
          await page
            .getByRole("button", { name: "Compare clans", exact: true })
            .click();
          await page
            .getByRole("button", { name: "Lazy CWL", exact: true })
            .click();
        }
        const card = page
          .locator(
            mode === "accounts"
              ? ".roster-player-card"
              : ".compare-account:visible",
          )
          .filter({ hasText: "#QG02CY8LG" })
          .first();
        await card.waitFor();
        const measured = await card.evaluate((element) => {
          const row = element.querySelector(".player-card-meta");
          const core = row.querySelector(".player-card-meta-core");
          const pool = row.querySelector(".player-card-meta-pool");
          const lock = row.querySelector("svg");
          const range = document.createRange();
          range.selectNodeContents(core);
          const clone = element.cloneNode(true);
          clone.querySelector(".player-card-meta-core").textContent =
            "TH18 · #P2Y";
          element.parentElement.append(clone);
          const shortHeight = clone.getBoundingClientRect().height;
          clone.remove();
          return {
            whiteSpace: getComputedStyle(row).whiteSpace,
            boxes: row.getClientRects().length,
            textLineTops: [
              ...new Set(
                [...range.getClientRects()].map(
                  (rect) => Math.round(rect.top * 100) / 100,
                ),
              ),
            ],
            height: element.getBoundingClientRect().height,
            shortHeight,
            coreWidth: core.clientWidth,
            coreScroll: core.scrollWidth,
            lockBottom: lock.getBoundingClientRect().bottom,
            rowBottom: row.getBoundingClientRect().bottom,
            lockRight: lock.getBoundingClientRect().right,
            rowRight:
              row.getBoundingClientRect().right -
              parseFloat(getComputedStyle(row).paddingRight),
            poolOverflow: getComputedStyle(pool).textOverflow,
          };
        });
        assert.equal(measured.whiteSpace, "nowrap");
        assert.equal(measured.boxes, 1, `${width} ${mode}: metadata wrapped`);
        assert.equal(
          measured.textLineTops.length,
          1,
          `${width} ${mode}: text spans multiple lines`,
        );
        assert.equal(
          measured.height,
          measured.shortHeight,
          `${width} ${mode}: long tag changes card height`,
        );
        assert(measured.coreWidth >= measured.coreScroll, "tag clipped");
        assert(
          measured.lockBottom <= measured.rowBottom &&
            measured.lockRight <= measured.rowRight + 1,
          `${width} ${mode}: lock clipped or displaced ${JSON.stringify(measured)}`,
        );
        assert.equal(measured.poolOverflow, "ellipsis");
        assert.equal(
          await page.evaluate(
            () => document.documentElement.scrollWidth > innerWidth,
          ),
          false,
        );
        results.push({ width, mode, ...measured });
      }
      await page.close();
    }
    console.log(JSON.stringify(results, null, 2));
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
