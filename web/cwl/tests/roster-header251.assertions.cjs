/* Shared D6 layout assertions. Isolated fixtures only; DOM reads, real UI actions. */
const assert = require("node:assert/strict");
async function checkRosterHeader251(
  page,
  { count, density = false, interactions = true } = {},
) {
  await page.evaluate(async () => {
    await document.fonts.ready;
    await new Promise((resolve) =>
      requestAnimationFrame(() => requestAnimationFrame(resolve)),
    );
  });
  const metrics = await page.evaluate(() => {
    const rect = (selector) => {
      const element = document.querySelector(selector);
      if (!element) return null;
      const box = element.getBoundingClientRect();
      return {
        x: box.x,
        y: box.y,
        width: box.width,
        height: box.height,
        bottom: box.bottom,
      };
    };
    return {
      width: innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      banner: !!document.querySelector(".fixture-banner"),
      title: rect(".roster-header-title-row"),
      steps: rect(".roster-header .cwl-step-strip"),
      summary: rect(".roster-header-overview"),
      draft: rect(".roster-header > .publication-awareness"),
      tabs: rect(".roster-workflow-nav"),
      toolbar: rect(".roster-filters-toolbar"),
      search: rect('.roster-filters-toolbar input[type="search"]'),
      clans: rect(".roster-clan-chips"),
      count: rect(".roster-list-heading"),
      firstAccount: rect(".roster-player-card"),
    };
  });
  assert(
    metrics.title &&
      metrics.summary &&
      metrics.tabs &&
      metrics.toolbar &&
      metrics.count &&
      metrics.firstAccount,
  );
  assert(
    metrics.summary.y >= metrics.title.bottom,
    "Summary must follow title/actions",
  );
  if (metrics.steps) {
    assert(
      metrics.steps.y >= metrics.title.bottom,
      "B2 steps must remain below title",
    );
    assert(
      metrics.summary.y >= metrics.steps.bottom,
      "Summary must follow B2 steps",
    );
  }
  if (metrics.draft) {
    assert(
      metrics.draft.y >= metrics.summary.bottom,
      "Draft/Review must follow summary",
    );
    assert(
      metrics.tabs.y >= metrics.draft.bottom,
      "Page tabs must follow Draft/Review",
    );
  } else assert(metrics.tabs.y >= metrics.summary.bottom);
  assert(
    metrics.toolbar.y >= metrics.tabs.bottom,
    "Toolbar must follow page tabs",
  );
  if (metrics.clans) {
    assert(
      metrics.clans.y >= metrics.toolbar.bottom,
      "Clan rail must follow toolbar",
    );
    assert(
      metrics.count.y >= metrics.clans.bottom,
      "Count/Select must follow clan rail",
    );
  }
  assert(
    metrics.firstAccount.y >= metrics.count.bottom,
    "List must follow count/Select",
  );
  assert(
    metrics.documentWidth <= metrics.width,
    "Document must not scroll horizontally",
  );
  if (count === 125 && metrics.width === 360) {
    assert.equal(
      metrics.banner,
      false,
      "Density fixture must not show development banner",
    );
    assert(
      metrics.firstAccount.y <= 560,
      `First account y=${metrics.firstAccount.y} exceeds560`,
    );
  }
  const tabs = page.locator('.roster-workspace-navigation [role="tablist"]');
  assert.equal(await tabs.count(), 1, "Exactly one page-tab row");
  assert.equal(await tabs.getByRole("tab").count(), 4);
  const disclosure = page.locator(".roster-header-summary > summary");
  assert(
    (await disclosure.innerText()).includes("Roster tools"),
    "Occasional controls need a visible disclosure label",
  );
  const disclosureBox = await disclosure.boundingBox();
  assert(disclosureBox.width >= 44 && disclosureBox.height >= 44);
  const toolbar = page.locator(".roster-filters-toolbar");
  const pool = toolbar.getByRole("group", {
    name: "CWL account pool",
    exact: true,
  });
  assert.equal(await pool.count(), 1, "Pool is a toolbar filter");
  for (const button of await pool.getByRole("button").all()) {
    const box = await button.boundingBox();
    assert(
      box.width >= 44 && box.height >= 44,
      "Pool filter targets must be44px",
    );
  }
  const add = toolbar.getByRole("button", { name: "Add signup", exact: true });
  assert.equal(
    await page.getByRole("button", { name: "Add signup", exact: true }).count(),
    1,
  );
  assert((await add.getAttribute("class")).includes("is-primary"));
  if (metrics.width <= 650) {
    const controlBoxes = await Promise.all([
      pool.boundingBox(),
      toolbar.getByRole("button", { name: /^Filters/ }).boundingBox(),
      toolbar.getByRole("button", { name: /^Sort:/ }).boundingBox(),
      add.boundingBox(),
    ]);
    for (const box of controlBoxes) {
      assert(box.width >= 44 && box.height >= 44, "Toolbar targets remain44px");
      assert(
        box.x >= 0 && box.x + box.width <= metrics.width + 1,
        "Toolbar controls stay within viewport",
      );
    }
    assert(
      (await add.innerText()).includes("Add signup"),
      "Primary keeps full visible label",
    );
    assert(
      await add.evaluate(
        (element) => element.scrollWidth <= element.clientWidth + 1,
      ),
      "Primary label must not clip",
    );
    const clanCards = page.locator(".roster-clan-chips .roster-clan-chip");
    for (const card of await clanCards.all()) {
      assert(
        await card.evaluate((element) => {
          const box = element.getBoundingClientRect();
          if (box.width < 44 || box.height < 44) return false;
          return [
            ...element.querySelectorAll(
              ".roster-clan-chip-top, .roster-clan-chip-meta, .roster-ui-progress",
            ),
          ].every((child) => {
            const rect = child.getBoundingClientRect();
            return (
              rect.top >= box.top &&
              rect.bottom <= box.bottom + 1 &&
              rect.left >= box.left &&
              rect.right <= box.right + 1 &&
              child.scrollWidth <= child.clientWidth + 1
            );
          });
        }),
        "Clan name/count/Total/weighed/progress remain contained in44px targets",
      );
    }
    assert(
      controlBoxes.every((box) => box.y >= metrics.search.bottom - 1),
      "Search occupies first toolbar row",
    );
    assert(
      Math.max(...controlBoxes.map((box) => box.y)) -
        Math.min(...controlBoxes.map((box) => box.y)) <=
        2,
      "Other toolbar controls must share second row",
    );
  }
  if (!interactions) return metrics;
  const originalUrl = page.url();
  const before = await (
    await page.request.get(new URL("/qa/state", page.url()).href)
  ).json();
  await pool.getByRole("button", { name: "Main CWL", exact: true }).click();
  assert.equal(
    page.url(),
    originalUrl,
    "Existing pool preference must not rewrite the page URL",
  );
  assert.equal(
    await pool
      .getByRole("button", { name: "Main CWL", exact: true })
      .getAttribute("aria-pressed"),
    "true",
  );
  const stored = await page.evaluate(() =>
    JSON.parse(sessionStorage.getItem("wu-roster-1-release-v1")),
  );
  assert.equal(stored.pool, "main");
  const select = page
    .locator(".roster-list-heading")
    .getByRole("button", { name: "Select", exact: true });
  const roster = await (
    await page.request.get(
      new URL("/api/cwl/seasons/1/roster", page.url()).href,
    )
  ).json();
  const available = roster.accounts.filter(
    (account) => account.pool === "main" && !account.kept,
  ).length;
  for (const size of [15, 30]) {
    await select.click();
    await page
      .getByRole("menuitem", { name: `Select ${size}`, exact: true })
      .click();
    assert(
      (await page.locator(".roster-list-count-text").innerText()).includes(
        `${Math.min(size, available)} selected`,
      ),
    );
  }
  await select.click();
  await page
    .getByRole("menuitem", { name: "Clear selection", exact: true })
    .click();
  await select.click();
  assert.equal(
    await page
      .getByRole("menuitem", { name: "Clear selection", exact: true })
      .count(),
    0,
  );
  await page.keyboard.press("Escape");
  await pool.getByRole("button", { name: "All accounts", exact: true }).click();
  const after = await (
    await page.request.get(new URL("/qa/state", page.url()).href)
  ).json();
  assert.deepEqual(
    after.current,
    before.current,
    "Pool/Select interactions changed protected fixture state",
  );
  await page.keyboard.press("Control+Home");
  await page.waitForFunction(() => window.scrollY === 0);
  return metrics;
}
module.exports = { checkRosterHeader251 };
