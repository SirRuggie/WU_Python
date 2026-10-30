/* Isolated Assign and Balance total-weight layout check; never applies a plan. */
const assert = require("node:assert/strict");
const { chromium } = require("playwright");

const port = Number(process.argv[2] || 8987);
assert(Number.isInteger(port) && port >= 8900 && port <= 8999);
const origin = `http://127.0.0.1:${port}`;
const shots = process.env.WU_LAYOUT_SCREENSHOTS;

async function state() {
  const response = await fetch(`${origin}/qa/state`);
  assert.equal(response.status, 200);
  return response.json();
}

async function assertNoOverflow(page, label) {
  const geometry = await page.evaluate(() => ({
    viewport: innerWidth,
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
  }));
  assert(
    geometry.document <= geometry.viewport + 1,
    `${label}: document overflows: ${JSON.stringify(geometry)}`,
  );
  assert(
    geometry.body <= geometry.viewport + 1,
    `${label}: body overflows: ${JSON.stringify(geometry)}`,
  );
  return geometry;
}

async function inspectTotal(locator, expected, label) {
  const text = (await locator.innerText()).replace(/\s+/g, " ");
  assert.match(text, expected, `${label}: wrong total`);
  const geometry = await locator.evaluate((node) => {
    const style = getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    const range = document.createRange();
    range.selectNodeContents(node);
    const lineTops = [...range.getClientRects()]
      .map((part) => Math.round(part.top))
      .filter((top, index, all) => all.indexOf(top) === index);
    return {
      lineTops,
      text: node.textContent.trim(),
      width: rect.width,
      height: rect.height,
      lineHeight: parseFloat(style.lineHeight),
      scrollWidth: node.scrollWidth,
      clientWidth: node.clientWidth,
    };
  });
  assert(
    geometry.scrollWidth <= geometry.clientWidth + 1,
    `${label}: total overflows: ${JSON.stringify(geometry)}`,
  );
  assert(
    geometry.lineTops.length <= 1,
    `${label}: total wraps: ${JSON.stringify(geometry)}`,
  );
  return geometry;
}

async function openRoster(browser, width, errors, writes) {
  const page = await browser.newPage({
    viewport: { width, height: width === 360 ? 800 : 1000 },
    reducedMotion: "reduce",
  });
  page.on("pageerror", (error) => errors.push(String(error)));
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.origin !== origin && url.hostname !== "cdn.discordapp.com") {
      errors.push(`External request attempted: ${request.url()}`);
    }
    if (request.method() !== "GET") {
      writes.push({ method: request.method(), path: url.pathname });
    }
  });
  await page.route("**/*", (route) => {
    const url = new URL(route.request().url());
    if (url.origin === origin) return route.continue();
    if (url.hostname === "cdn.discordapp.com") {
      return route.fulfill({
        contentType: "image/svg+xml",
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"/>',
      });
    }
    return route.abort();
  });
  await page.goto(`${origin}/cwl/roster?season=1`);
  await page.getByRole("button", { name: "Open local test session" }).click();
  await page.locator(".roster-player-card").first().waitFor();
  const seededTotal = await page.evaluate(async () => {
    const response = await fetch("/api/cwl/seasons/1/roster");
    const roster = await response.json();
    return roster.accounts
      .filter((account) => account.assigned_clan_tag === "#P2Y")
      .reduce((sum, account) => sum + (account.effective_weight ?? 0), 0);
  });
  assert.equal(seededTotal, 4512500, "fixture total is not 4,512.5k");
  return page;
}

async function runWidth(browser, width, errors, writes) {
  const page = await openRoster(browser, width, errors, writes);
  const geometry = {};
  try {
    geometry.roster = await assertNoOverflow(page, `${width} roster`);
    await page
      .getByRole("searchbox", { name: "Search accounts" })
      .fill("Blaze 002");
    await page
      .getByRole("checkbox", { name: "Select Blaze 002 for bulk actions" })
      .check();
    await page
      .getByRole("region", { name: "Selected roster actions" })
      .getByRole("button", { name: "Assign", exact: true })
      .click();

    const assign = page.getByRole("dialog", {
      name: "Assign selected accounts",
    });
    await assign.waitFor();
    const assignRow = assign
      .locator(".roster-assign-clan")
      .filter({ hasText: "Warriors Unite!" });
    await assignRow.waitFor();
    const assignTotal = assignRow
      .locator(".roster-assign-clan-meta > span")
      .first();
    geometry.assignTotal = await inspectTotal(
      assignTotal,
      /Current total 4,512\.5k/,
      `${width} Assign`,
    );
    assert.match(await assign.innerText(), /no weights yet/i);
    geometry.assign = await assertNoOverflow(page, `${width} Assign`);
    await assignRow.scrollIntoViewIfNeeded();
    if (shots) await page.screenshot({ path: `${shots}/${width}-assign.png` });
    await assign.getByRole("button", { name: "Close panel" }).click();

    await page
      .getByRole("region", { name: "Selected roster actions" })
      .getByRole("button", { name: "Balance", exact: true })
      .click();
    const balance = page.getByRole("dialog", { name: "Balance across clans" });
    await balance.waitFor();
    const target = balance
      .locator(".roster-plan-clan")
      .filter({ hasText: "Warriors Unite!" });
    await target.waitFor();
    geometry.balanceTotal = await inspectTotal(
      target.locator("small").first(),
      /Total 4,512\.5k/,
      `${width} Balance target`,
    );
    assert.match(await balance.innerText(), /no weights yet/i);
    await target.locator('input[type="checkbox"]').check();
    await balance
      .locator(".roster-plan-clan")
      .filter({ hasText: "Crystal Keep" })
      .locator('input[type="checkbox"]')
      .check();
    geometry.balance = await assertNoOverflow(page, `${width} Balance`);
    await target.scrollIntoViewIfNeeded();
    if (shots)
      await page.screenshot({ path: `${shots}/${width}-balance-target.png` });

    await balance
      .getByRole("button", { name: "Preview placements", exact: true })
      .click();
    const totals = balance.locator(".roster-plan-totals");
    await totals.waitFor();
    const previewText = (await totals.innerText()).replace(/\s+/g, " ");
    assert.match(previewText, /Total/);
    assert.match(previewText, /4,512\.5k/);
    assert.doesNotMatch(previewText, /Avg\s+\d/i);
    geometry.previewTotals = [];
    for (const [index, row] of (await totals.locator("div").all()).entries()) {
      geometry.previewTotals.push(
        await inspectTotal(
          row.locator("span").last(),
          /Total/,
          `${width} Balance preview row ${index + 1}`,
        ),
      );
    }
    geometry.preview = await assertNoOverflow(page, `${width} Balance preview`);
    await totals.scrollIntoViewIfNeeded();
    if (shots)
      await page.screenshot({ path: `${shots}/${width}-balance-preview.png` });
    return { width, geometry, previewText };
  } finally {
    await page.close();
  }
}

(async () => {
  const before = await state();
  assert.equal(before.current.account_count, 125);
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH || "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox"],
  });
  const errors = [];
  const writes = [];
  try {
    const results = [];
    for (const width of [360, 1440]) {
      results.push(await runWidth(browser, width, errors, writes));
    }
    const after = await state();
    assert.deepEqual(after.current, before.current, "fixture state changed");
    assert.deepEqual(
      writes.filter(
        ({ path }) =>
          path !== "/api/cwl/dev/login" &&
          path !== "/api/cwl/seasons/1/roster/auto-preview",
      ),
      [],
      "unexpected application write",
    );
    assert(
      writes.some(
        ({ method, path }) =>
          method === "POST" &&
          path === "/api/cwl/seasons/1/roster/auto-preview",
      ),
      "Balance preview was not exercised",
    );
    assert.deepEqual(errors, []);
    console.log(
      JSON.stringify(
        {
          ok: true,
          results,
          countsBefore: before.current.season_counts,
          countsAfter: after.current.season_counts,
          writes,
          errors,
        },
        null,
        2,
      ),
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
