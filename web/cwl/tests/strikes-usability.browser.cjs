/* Own browser-only StrikesPreview transport; no production or live writes. */
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const origin = `http://127.0.0.1:${Number(process.argv[2])}`;
const output =
  process.env.WU_STRIKES_LAYOUT_OUTPUT || "/tmp/wu-strikes-usability";
fs.mkdirSync(output, { recursive: true });
// Phones list accounts as cards; wider layouts keep the table rows.
const ENTRY = ".strike-activity-entry, .strike-activity-card";
// Phones list the views in a select; wider layouts keep the pill tabs.
async function chooseView(page, label) {
  const select = page.getByLabel("View", { exact: true });
  if (await select.count()) {
    const value = await select.evaluate(
      (node, wanted) =>
        [...node.options].find((option) =>
          option.textContent.startsWith(wanted),
        ).value,
      label,
    );
    await select.selectOption(value);
  } else {
    await page.getByRole("button", { name: new RegExp(`^${label} `) }).click();
  }
  await page.locator("[data-strike-player]").first().waitFor();
}
async function activeView(page) {
  const select = page.getByLabel("View", { exact: true });
  if (await select.count())
    return select.evaluate((node) => node.selectedOptions[0].textContent);
  return page
    .locator('.strike-activity-tabs button[aria-pressed="true"]')
    .textContent();
}
async function findSlotsPanel(page, width, count) {
  await chooseView(page, "Replacements");
  await page.locator("[data-strike-player]").first().waitFor();
  // The incumbent fixture resolves API reads in window.fetch. Count those fake
  // reads, rather than treating the absence of real HTTP traffic as proof.
  await page.evaluate(() => {
    const original = window.fetch;
    window.findSlotsFixtureRequests = [];
    window.fetch = (...args) => {
      window.findSlotsFixtureRequests.push({
        url: String(args[0]),
        method: args[1]?.method || "GET",
      });
      return original(...args);
    };
  });
  const measure = () =>
    page.evaluate(() => {
      const first = document.querySelector("[data-strike-player]");
      const firstAccountTop = first.getBoundingClientRect().top;
      const controls = [
        ...document.querySelectorAll("button,input,summary,a[href]"),
      ].filter((node) => {
        if (node.closest("[hidden]")) return false;
        const closed = node.closest("details:not([open])");
        if (closed && !closed.querySelector(":scope > summary")?.contains(node))
          return false;
        const rect = node.getBoundingClientRect();
        const style = getComputedStyle(node);
        return (
          rect.width > 0 &&
          rect.height > 0 &&
          style.display !== "none" &&
          style.visibility !== "hidden" &&
          rect.top < firstAccountTop
        );
      });
      return {
        visibleControlsAboveFirstAccount: controls.length,
        firstAccountTop,
        controls: controls.map(
          (node) =>
            node.getAttribute("aria-label") || node.textContent || node.tagName,
        ),
        requests: window.findSlotsFixtureRequests.slice(),
      };
    });
  const closed = await measure();
  assert.equal(await page.locator(".strike-find-slots-toggle").count(), 0);
  assert.equal(await page.locator("dialog[open]").count(), 0);
  assert.equal(
    await page.getByLabel("Weights", { exact: true }).count(),
    0,
    "The weights field stays behind the Find slots button",
  );
  assert.equal(await page.getByLabel("Find clan").count(), 0);
  if (width <= 760)
    await page.screenshot({
      path: path.join(output, `${width}-${count}-slots-closed.png`),
    });
  const opener = page.getByRole("button", { name: "Find slots", exact: true });
  const url = page.url();
  await opener.click();
  await page.getByLabel("Weights", { exact: true }).waitFor();
  assert.equal(page.url(), url);
  assert.equal((await measure()).requests.length, 0, "Opening never searches");
  await page.getByLabel("Weights", { exact: true }).fill("143, 173, 150");
  assert.equal((await measure()).requests.length, 0, "Typing never searches");
  await page.locator(".strike-find-slots-top button.primary").click();
  await page.locator(".strike-slot-group").first().waitFor();
  const results = await page.locator(".strike-slot-group").allTextContents();
  // A search writes its weights to the link; closing and reopening must not.
  const searchedUrl = page.url();
  const searched = await measure();
  assert.equal(
    searched.requests.filter((request) =>
      request.url.includes("/strikes/replacements"),
    ).length,
    1,
  );
  assert(searched.requests.every((request) => request.method === "GET"));
  await page.screenshot({
    path: path.join(output, `${width}-${count}-slots-open-results.png`),
  });
  await page
    .locator("dialog[open]")
    .getByRole("button", { name: "Close panel", exact: true })
    .click();
  await page.waitForFunction(() => !document.querySelector("dialog[open]"));
  await opener.click();
  assert.equal(
    await page.getByLabel("Weights", { exact: true }).inputValue(),
    "143, 173, 150",
  );
  assert.deepEqual(
    await page.locator(".strike-slot-group").allTextContents(),
    results,
  );
  assert.deepEqual((await measure()).requests, searched.requests);
  assert.equal(page.url(), searchedUrl);
  await page
    .locator("dialog[open]")
    .getByRole("button", { name: "Close panel", exact: true })
    .click();
  await page.waitForFunction(() => !document.querySelector("dialog[open]"));
  // Filters panel in the Replacements view: no clan search, bounded content.
  await page.getByRole("button", { name: "Filters", exact: true }).click();
  await page.getByRole("dialog").waitFor();
  assert.equal(
    await page.getByRole("searchbox", { name: "Find clan" }).count(),
    0,
  );
  const filtersContentHeight = await page
    .locator("dialog .strike-activity-more")
    .evaluate((node) => node.scrollHeight);
  await page.getByRole("button", { name: "Close panel", exact: true }).click();
  await page.waitForFunction(() => !document.querySelector("dialog[open]"));
  const record = {
    width,
    count,
    firstAccountTop: closed.firstAccountTop,
    filtersContentHeight,
    visibleControlsAboveFirstAccount: closed.visibleControlsAboveFirstAccount,
    controls: closed.controls,
  };
  if (width === 360) {
    console.log(
      `replacements ${width}x800 count=${count}: first row top ${closed.firstAccountTop}px, Filters content height ${filtersContentHeight}px`,
    );
    assert(filtersContentHeight > 0, JSON.stringify(record));
    assert(
      closed.firstAccountTop <= 450,
      `First account row starts at ${closed.firstAccountTop}px`,
    );
  }
  return record;
}
(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    args: ["--no-sandbox"],
  });
  const evidence = [];
  const disclosureEvidence = [];
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
        assert.match(await activeView(page), /^Not attacking/);
        assert(
          await page
            .locator(".strike-activity-rule")
            .filter({ hasText: "3+ wars without attacking" })
            .count(),
        );
        if (count === 560 && [360, 1440].includes(width))
          await page.screenshot({
            path: path.join(output, `${width}-not-attacking.png`),
          });
        await chooseView(page, "All");
        assert.equal(await page.locator("[data-strike-player]").count(), 25);
        const metrics = await page.evaluate(
          (ENTRY) => ({
            width: innerWidth,
            scrollWidth: document.documentElement.scrollWidth,
            toolbar: document
              .querySelector(".strike-activity-toolbar")
              .getBoundingClientRect().height,
            firstRowTop: document.querySelector(ENTRY).getBoundingClientRect()
              .top,
            row: document.querySelector(ENTRY).getBoundingClientRect().height,
            rowsInViewport: [...document.querySelectorAll(ENTRY)].filter(
              (row) => {
                const r = row.getBoundingClientRect();
                return r.top >= 0 && r.bottom <= innerHeight;
              },
            ).length,
            childrenFit: [...document.querySelectorAll(ENTRY)].every((row) =>
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
          }),
          ENTRY,
        );
        assert(metrics.scrollWidth <= width, JSON.stringify(metrics));
        assert(metrics.childrenFit, "Cell content overflows row geometry");
        assert(metrics.toolbar <= 60, JSON.stringify(metrics));
        assert(
          metrics.firstRowTop <= (width >= 1000 ? 300 : 450),
          JSON.stringify(metrics),
        );
        if (width >= 1000)
          assert(metrics.rowsInViewport >= 16, JSON.stringify(metrics));
        assert(metrics.row >= (width < 900 ? 70 : 44));
        assert(
          metrics.row <= (width < 900 ? 100 : 75),
          JSON.stringify(metrics),
        );
        if (width >= 760)
          assert.deepEqual(metrics.headings, [
            "Player",
            "TH",
            "Clan",
            "Member",
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
        assert.equal(
          await page.getByRole("searchbox", { name: "Find clan" }).count(),
          0,
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
              .querySelector(
                ".strike-activity-table tbody, .strike-activity-cards",
              )
              .getBoundingClientRect().top +
              scrollY -
              (innerWidth >= 900 ? 89 : 54),
          ),
        );
        await page.waitForTimeout(80);
        const scrolled = await page.evaluate(
          (ENTRY) => ({
            toolbarTop: document
              .querySelector(".strike-activity-toolbar")
              .getBoundingClientRect().top,
            headerTop: document
              .querySelector(".strike-activity-table th")
              ?.getBoundingClientRect().top,
            rows: [...document.querySelectorAll(ENTRY)].filter((row) => {
              const r = row.getBoundingClientRect();
              return (
                r.top >= (innerWidth >= 900 ? 88 : 54) &&
                r.bottom <= innerHeight
              );
            }).length,
          }),
          ENTRY,
        );
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
        if ([125, 560].includes(count) && [360, 1440].includes(width)) {
          disclosureEvidence.push(await findSlotsPanel(page, width, count));
          await chooseView(page, "All");
        }
        if (count === 560 && [360, 1440].includes(width)) {
          for (const [label, name] of [
            ["Inactive", "inactive"],
            ["Replacements", "replacements"],
          ]) {
            await chooseView(page, label);
            await page.screenshot({
              path: path.join(output, `${width}-${name}.png`),
            });
          }
        }
        // A link with slot weights reopens the Find slots panel once; close it.
        if (await page.locator("dialog[open]").count()) {
          await page
            .locator("dialog[open]")
            .getByRole("button", { name: "Close panel", exact: true })
            .click();
          await page.waitForFunction(
            () => !document.querySelector("dialog[open]"),
          );
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
    fs.writeFileSync(
      path.join(output, "find-slots-disclosure.json"),
      JSON.stringify(disclosureEvidence, null, 2),
    );
    console.log(JSON.stringify(evidence));
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
