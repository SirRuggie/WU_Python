/* Run against the isolated 125-account fixture, never production:
 * node tests/player-card-line2.browser.cjs 8949
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
      await page.route("**/*", (route) => {
        const url = new URL(route.request().url());
        // Locally fulfilled image: exercise the real img element without external traffic.
        if (
          url.hostname === "cdn.discordapp.com" &&
          url.pathname.startsWith("/emojis/")
        )
          return route.fulfill({
            contentType: "image/svg+xml",
            body: '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="#f0d080"/><path d="M0 0L64 64M64 0L0 64" stroke="#181818" stroke-width="4"/></svg>',
          });
        return url.origin === `http://127.0.0.1:${port}`
          ? route.continue()
          : route.abort();
      });
      await page.goto(`http://127.0.0.1:${port}/cwl/roster?season=1`);
      await page
        .getByRole("button", { name: "Open local test session" })
        .click();
      await page.locator(".roster-player-card").first().waitFor();
      if (width === 360 || width === 1440) {
        const attentionLines = page.locator(".signup-activity-line");
        await attentionLines.first().waitFor();
        assert.equal(
          await attentionLines.count(),
          2,
          "expected separate review and shortage alerts",
        );
        const reviewLine = page.locator(
          ".signup-activity-line:not(.is-danger)",
        );
        const shortageLine = page.locator(".signup-activity-line.is-danger");
        assert.equal(
          await reviewLine.count(),
          1,
          "expected one amber review alert",
        );
        assert.equal(
          await shortageLine.count(),
          1,
          "expected one red shortage alert",
        );
        const alertOrder = await page.evaluate(() => {
          const status = document.querySelector(".publication-awareness");
          const review = document.querySelector(
            ".signup-activity-line:not(.is-danger)",
          );
          const shortage = document.querySelector(
            ".signup-activity-line.is-danger",
          );
          return [status, review, shortage].map(
            (node) => node?.getBoundingClientRect().top ?? null,
          );
        });
        assert(
          alertOrder.every((top) => top !== null),
          "publication and both attention lines must be visible",
        );
        assert(
          alertOrder[0] < alertOrder[1] && alertOrder[1] < alertOrder[2],
          "expected status, review, then shortage order",
        );
        await reviewLine.click();
        await page.locator(".signup-activity-panel").waitFor();
        const buttons = await page
          .locator(".signup-activity-actions .roster-ui-button")
          .evaluateAll((nodes) =>
            nodes.map((node) => {
              const style = getComputedStyle(node);
              return {
                height: node.getBoundingClientRect().height,
                color: style.color,
                fill: style.webkitTextFillColor,
                background: style.backgroundColor,
                border: style.border,
                radius: style.borderRadius,
                font: style.font,
                decoration: style.textDecorationLine,
                text: node.textContent,
              };
            }),
          );
        assert.equal(buttons.length, 3);
        for (const button of buttons) {
          assert.equal(button.height, 44, `${button.text}: action height`);
          for (const key of [
            "color",
            "fill",
            "background",
            "border",
            "radius",
            "font",
            "decoration",
          ])
            assert.equal(
              button[key],
              buttons[0][key],
              `${button.text}: inconsistent ${key}`,
            );
        }
        if (process.env.WU_LAYOUT_SCREENSHOTS)
          await page.screenshot({
            path: `${process.env.WU_LAYOUT_SCREENSHOTS}/panel-${width}.jpg`,
            type: "jpeg",
            quality: 80,
          });
        await page
          .getByRole("button", { name: "Close panel", exact: true })
          .click();
      }

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
        if (width >= 900 && mode === "accounts") {
          const columns = card.locator(".roster-account-columns");
          await columns.waitFor();
          const firstRow = await columns.evaluate((row) => {
            const fields = ["name", "pool", "assigned", "now", "weight"];
            return Object.fromEntries(
              fields.map((field) => {
                const cell = row.querySelector(
                  `.roster-account-column-${field}`,
                );
                return [
                  field,
                  {
                    text: cell?.innerText.trim() || "",
                    left: cell
                      ? Math.round(cell.getBoundingClientRect().left)
                      : null,
                  },
                ];
              }),
            );
          });
          assert.deepEqual(Object.keys(firstRow), [
            "name",
            "pool",
            "assigned",
            "now",
            "weight",
          ]);
          assert(
            firstRow.name.text.includes("#QG02CY8LG"),
            "desktop name column includes the player tag",
          );
          assert(
            firstRow.assigned.text.length > 0,
            "desktop assigned-clan column is populated",
          );
          assert(
            firstRow.now.text.length > 0,
            "desktop current-clan column is populated",
          );
          assert.equal(
            await card
              .locator(".roster-player-body")
              .evaluate((node) => getComputedStyle(node).display),
            "block",
            "desktop account row body must use column layout",
          );
          assert.equal(
            await card
              .locator(
                ".roster-player-body > .player-card-top:visible, .roster-player-body > .player-card-meta:visible, .roster-player-body > .player-clan-status:visible",
              )
              .count(),
            0,
            "phone card lines should be hidden in desktop roster rows",
          );
          await page
            .getByPlaceholder("Name, player tag or Discord ID")
            .fill("Aurora Champion");
          const longNameCard = page
            .locator(".roster-player-card:visible")
            .filter({ hasText: "Aurora Champion" })
            .first();
          await longNameCard.waitFor();
          assert.equal(
            await longNameCard
              .locator(".roster-account-column-name")
              .innerText()
              .then((text) => text.includes("Aurora Champion")),
            true,
          );
          assert.match(
            await longNameCard
              .locator(".roster-account-column-assigned")
              .innerText(),
            /Morning Woods!/,
          );
          await page
            .getByPlaceholder("Name, player tag or Discord ID")
            .fill("");
          const alignedColumns = await page
            .locator(".roster-player-card:visible .roster-account-columns")
            .evaluateAll((rows) => {
              const fields = ["name", "pool", "assigned", "now", "weight"];
              return rows.slice(0, 2).map((row) =>
                fields.map((field) => {
                  const cell = row.querySelector(
                    `.roster-account-column-${field}`,
                  );
                  return cell
                    ? Math.round(cell.getBoundingClientRect().left)
                    : null;
                }),
              );
            });
          assert.equal(
            alignedColumns.length,
            2,
            "expected multiple desktop rows for alignment check",
          );
          for (let index = 0; index < 5; index++)
            assert.equal(
              alignedColumns[0][index],
              alignedColumns[1][index],
              `desktop column ${index} does not align`,
            );
          if (process.env.WU_LAYOUT_SCREENSHOTS)
            await card.screenshot({
              path: `${process.env.WU_LAYOUT_SCREENSHOTS}/desktop-columns-${mode}.jpg`,
              type: "jpeg",
              quality: 90,
            });
          assert.equal(
            await page.evaluate(
              () => document.documentElement.scrollWidth > innerWidth,
            ),
            false,
            "desktop roster page overflows horizontally",
          );
          results.push({
            width,
            mode,
            desktopColumns: firstRow,
            alignedColumns,
          });
          continue;
        }
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
          const imageBounds = icon.getBoundingClientRect();
          let iconClipped = false;
          for (
            let node = icon.parentElement;
            node && node !== element;
            node = node.parentElement
          ) {
            const style = getComputedStyle(node),
              bounds = node.getBoundingClientRect();
            if (
              [style.overflowY, style.overflowX].some((value) =>
                ["hidden", "clip", "auto", "scroll"].includes(value),
              ) &&
              (imageBounds.top < bounds.top - 0.1 ||
                imageBounds.bottom > bounds.bottom + 0.1 ||
                imageBounds.left < bounds.left - 0.1 ||
                imageBounds.right > bounds.right + 0.1)
            )
              iconClipped = true;
          }
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
            imageLoaded:
              icon instanceof HTMLImageElement &&
              icon.complete &&
              icon.naturalWidth > 0,
            iconClipped,
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
        assert.equal(
          measured.imageLoaded,
          true,
          "real TH image element must load local stub",
        );
        assert.equal(
          measured.iconClipped,
          false,
          "TH image is clipped by an ancestor",
        );
        if (
          process.env.WU_LAYOUT_SCREENSHOTS &&
          (width === 360 || width === 1440)
        )
          await card.screenshot({
            path: `${process.env.WU_LAYOUT_SCREENSHOTS}/${mode}-${width}.jpg`,
            type: "jpeg",
            quality: 90,
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
