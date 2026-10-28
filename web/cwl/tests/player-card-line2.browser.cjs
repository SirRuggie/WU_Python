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
          const body = element.querySelector(".player-card-body");
          const contentLeft =
            body.getBoundingClientRect().left +
            parseFloat(getComputedStyle(body).paddingLeft);
          const name = element.querySelector(".player-card-name");
          const icon = name.querySelector(
            ".town-hall-icon, .town-hall-fallback",
          );
          const line3 = element.querySelector(".player-clan-status");
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
            iconFirst: !!icon && name.firstElementChild.contains(icon),
            metaIndent: row.getBoundingClientRect().left - contentLeft,
            clanIndent: line3.getBoundingClientRect().left - contentLeft,
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
        assert(
          measured.iconFirst,
          "TH icon must be in the name row before the name",
        );
        assert(
          Math.abs(measured.metaIndent) < 1,
          "line 2 retains an icon-column indent",
        );
        assert(
          Math.abs(measured.clanIndent) < 1,
          "line 3 retains an icon-column indent",
        );
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
        const fitCases =
          width === 360
            ? await card.evaluate((element) => {
                const row = element.querySelector(".roster-player-placement");
                const saved = row.innerHTML;
                const results = [];
                for (const [assigned, current, age] of [
                  ["Morning Woods!", "Warriors Unite!", "just now"],
                  ["W. U. Lazy .127", "ClashofThrones", "15m ago"],
                ]) {
                  row.className = "roster-player-placement is-elsewhere";
                  row.innerHTML = `<strong>${assigned}</strong><span class="roster-player-current">→ <span class="player-current-clan is-elsewhere">${current}</span> · ${age}</span>`;
                  const suffix = row.querySelector(".roster-player-current");
                  results.push({
                    assigned,
                    current,
                    age,
                    oneLine:
                      getComputedStyle(row).whiteSpace === "nowrap" &&
                      row.getBoundingClientRect().height <=
                        parseFloat(getComputedStyle(row).lineHeight) + 1,
                    fits: suffix.scrollWidth <= suffix.clientWidth,
                    available: suffix.clientWidth,
                    needed: suffix.scrollWidth,
                  });
                }
                row.innerHTML = saved;
                return results;
              })
            : [];
        assert(
          fitCases.every((result) => result.oneLine),
          "clan status wraps",
        );
        results.push({ width, mode, ...measured, fitCases });
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
