/* Isolated hotfix checks: no application writes; local dev-login only. */
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const port = Number(process.argv[2] || 8982);
assert(port >= 8900 && port <= 8999);
const origin = `http://127.0.0.1:${port}`;
const shots = process.env.WU_LAYOUT_SCREENSHOTS;
(async () => {
  const before = await (await fetch(`${origin}/qa/state`)).json();
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH || "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox"],
  });
  const results = [];
  try {
    for (const width of [360, 1440]) {
      const page = await browser.newPage({
        viewport: { width, height: width === 360 ? 800 : 1000 },
        reducedMotion: "reduce",
      });
      const errors = [];
      page.on("pageerror", (e) => errors.push(String(e)));
      await page.addInitScript(() => {
        window.__nativeConfirmCalls = 0;
        window.confirm = () => {
          window.__nativeConfirmCalls++;
          return false;
        };
      });
      await page.route("**/*", (route) => {
        const url = new URL(route.request().url());
        if (url.origin === origin) return route.continue();
        if (url.hostname === "cdn.discordapp.com")
          return route.fulfill({
            contentType: "image/svg+xml",
            body: '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"/>',
          });
        errors.push(`External request ${url.origin}`);
        return route.abort();
      });
      await page.goto(`${origin}/cwl/roster?season=1`);
      await page
        .getByRole("button", { name: "Open local test session" })
        .click();
      await page.locator(".roster-player-card").first().waitFor();
      const capacity = page.locator(".roster-capacity-alert");
      assert.equal(await capacity.count(), 1);
      assert.match(await capacity.innerText(), /2 clans have no capacity set/);
      const rules = before.current.rules.filter(
        (r) => r.pool && r.capacity !== 15 && r.capacity !== 30,
      );
      assert(rules.length >= 20);
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth > innerWidth,
        ),
        false,
      );
      if (shots) await page.screenshot({ path: `${shots}/${width}-top.png` });
      await page.locator(".roster-player-select input").first().check();
      for (const name of ["Main CWL", "Lazy CWL", "All accounts"]) {
        const tab = page
          .getByRole("group", { name: "CWL account pool", exact: true })
          .getByRole("button", { name, exact: true });
        await tab.click();
        assert.equal(await tab.getAttribute("aria-pressed"), "true");
        assert.equal(await page.locator(".confirm-dialog").count(), 0);
        assert.match(
          await page.locator(".roster-selection-dock").innerText(),
          /1 selected/,
        );
      }
      await page
        .getByRole("button", { name: "Clear selected accounts", exact: true })
        .click();
      await page.getByRole("button", { name: /Missing weights/ }).click();
      const queue = page.locator(".weight-queue");
      await queue.waitFor();
      const units = queue.getByRole("group", { name: "Enter weights as" });
      await units.waitFor();
      assert.equal(
        await queue.locator(".weight-queue-row .compact-weight-units").count(),
        0,
      );
      for (const name of ["Loot", "Full"]) {
        const box = await units
          .getByRole("button", { name, exact: true })
          .boundingBox();
        assert(box.height >= 44 && box.width >= 44);
      }
      const input = queue.locator('input[aria-label^="Loot for"]').first();
      await input.fill("150");
      assert.match(
        await input.evaluate(
          (node) => node.closest(".weight-queue-row").textContent,
        ),
        /Full weight must end in 000/,
      );
      assert(
        await input
          .locator("xpath=ancestor::*[contains(@class,'weight-queue-row')]")
          .getByRole("button", { name: "Save", exact: true })
          .isDisabled(),
      );
      await units.getByRole("button", { name: "Full", exact: true }).click();
      assert.equal(
        await queue
          .locator('input[aria-label^="Full weight for"]')
          .first()
          .inputValue(),
        "150",
      );
      await units.getByRole("button", { name: "Loot", exact: true }).click();
      await page
        .getByRole("button", { name: "Accounts & signups", exact: true })
        .click();
      const dialog = page.getByRole("dialog", { name: "Unsaved changes" });
      await dialog.waitFor();
      assert.match(await dialog.innerText(), /You have 1 unsaved weight\./);
      if (shots && width === 360)
        await page.screenshot({ path: `${shots}/360-popup.png` });
      await dialog
        .getByRole("button", { name: "Keep editing", exact: true })
        .click();
      assert.equal(await input.inputValue(), "150");
      await page
        .getByRole("button", { name: "Accounts & signups", exact: true })
        .click();
      await dialog.waitFor();
      await page.keyboard.press("Escape");
      await dialog.waitFor({ state: "hidden" });
      assert.equal(await input.inputValue(), "150");
      await page
        .getByRole("button", { name: "Accounts & signups", exact: true })
        .click();
      await dialog.waitFor();
      await page.mouse.click(1, 1);
      await dialog.waitFor({ state: "hidden" });
      assert.equal(await input.inputValue(), "150");
      await page.getByRole("button", { name: /^Season:/ }).click();
      await page
        .getByRole("menuitem", { name: "December 2026", exact: true })
        .click();
      await dialog.waitFor();
      await dialog
        .getByRole("button", { name: "Keep editing", exact: true })
        .click();
      assert.equal(await input.inputValue(), "150");
      assert.equal(new URL(page.url()).searchParams.get("season"), "1");
      if (width === 360)
        await page
          .getByRole("button", { name: "Open menu", exact: true })
          .click();
      await page
        .getByRole("navigation", { name: "Warriors United navigation" })
        .getByRole("button", { name: "Home", exact: true })
        .click();
      await dialog.waitFor();
      await dialog
        .getByRole("button", { name: "Keep editing", exact: true })
        .click();
      assert.equal(await input.inputValue(), "150");
      if (width === 360) {
        const closeMenu = page.getByRole("button", {
          name: "Close menu",
          exact: true,
        });
        if (await closeMenu.isVisible()) await closeMenu.click();
      }
      await queue.evaluate((node) =>
        window.scrollTo(
          0,
          window.scrollY + node.getBoundingClientRect().top - 74,
        ),
      );
      if (shots)
        await page.screenshot({ path: `${shots}/${width}-weights.png` });
      await page
        .getByRole("button", { name: "Accounts & signups", exact: true })
        .click();
      await dialog
        .getByRole("button", { name: "Discard", exact: true })
        .click();
      await page.locator(".roster-player-card").first().waitFor();
      await page.getByRole("button", { name: /Missing weights/ }).click();
      assert.equal(await input.inputValue(), "");
      await input.fill("175");
      await capacity
        .getByRole("button", { name: "Set in Clan settings" })
        .click();
      await dialog.waitFor();
      await dialog
        .getByRole("button", { name: "Discard", exact: true })
        .click();
      await page.locator(".clan-settings-row.is-selected").waitFor();
      await page.getByRole("button", { name: /Missing weights/ }).click();
      await input.fill("180");
      if (width === 360)
        await page
          .getByRole("button", { name: "Open menu", exact: true })
          .click();
      await page
        .getByRole("navigation", { name: "Warriors United navigation" })
        .getByRole("button", { name: "Home", exact: true })
        .click();
      await dialog
        .getByRole("button", { name: "Discard", exact: true })
        .click();
      await page.waitForURL((url) => !url.pathname.includes("roster"));
      assert.equal(await page.evaluate(() => window.__nativeConfirmCalls), 0);
      assert.deepEqual(errors, []);
      results.push({
        width,
        capacityLines: 1,
        missingCapacityClans: rules.length,
        unitTargets: 44,
        nativeConfirmCalls: 0,
        checks: [
          "two hosting clans only",
          "selection persists through All/Main/Lazy without dialog",
          "one top switch",
          "Loot/Full reinterpretation",
          "Keep editing",
          "Escape",
          "Discard tab",
          "Discard capacity link",
          "no overflow",
        ],
      });
      await page.close();
    }
    const after = await (await fetch(`${origin}/qa/state`)).json();
    assert.deepEqual(after.current, before.current);
    const writes = after.requests.filter(
      (r) => r.method !== "GET" && r.path !== "/api/cwl/dev/login",
    );
    assert.deepEqual(writes, []);
    console.log(
      JSON.stringify(
        {
          ok: true,
          results,
          countsBefore: before.current.season_counts,
          countsAfter: after.current.season_counts,
          writes,
        },
        null,
        2,
      ),
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
