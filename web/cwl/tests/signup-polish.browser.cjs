/* Isolated loopback fixture only; never submit a signup. */
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const port = Number(process.argv[2] || 8977);
assert(port >= 8900 && port <= 8999);
const base = `http://127.0.0.1:${port}`;
(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    args: ["--no-sandbox"],
  });
  const results = [],
    writes = [],
    errors = [];
  const out = process.env.WU_POLISH_EVIDENCE;
  if (out) fs.mkdirSync(out, { recursive: true });
  try {
    for (const width of [360, 1440]) {
      const page = await browser.newPage({
        viewport: { width, height: width === 360 ? 800 : 1000 },
      });
      page.on("pageerror", (e) => errors.push(String(e)));
      await page.route("**/*", (r) => {
        const u = new URL(r.request().url());
        if (u.origin !== base) return r.abort();
        if (
          r.request().method() !== "GET" &&
          u.pathname !== "/api/cwl/dev/login"
        )
          writes.push(u.pathname);
        return r.continue();
      });
      await page.goto(base + "/signup");
      await page
        .getByRole("button", { name: "Open local test session" })
        .click();
      await page.locator(".pool-choice-grid button").first().waitFor();
      await page
        .getByText("Loading linked accounts…", { exact: true })
        .waitFor({ state: "hidden" });
      await page.waitForTimeout(350);
      const measure = async (stage) => {
        const m = await page.evaluate(() => {
          const rect = (el) => {
            const r = el.getBoundingClientRect();
            return {
              top: r.top,
              bottom: r.bottom,
              height: r.height,
              width: r.width,
            };
          };
          const art = document.querySelector(".walkthrough-art"),
            current = document.querySelector(".signup-walkthrough .current"),
            first = document.querySelector(
              ".pool-choice-grid button,.account-list .account-card,.signup-review",
            );
          return {
            overflow: document.documentElement.scrollWidth > innerWidth,
            art: rect(art),
            loaded: art.complete && art.naturalWidth > 0,
            current: rect(current),
            first: first && rect(first),
            season: document.querySelector(".member-season-line").textContent,
            compact: [
              ...document.querySelectorAll(
                ".signup-walkthrough li:not(.current) button",
              ),
            ].map(rect),
          };
        });
        assert(!m.overflow);
        assert(m.loaded);
        assert(!m.season.toLowerCase().includes("draft"));
        assert(m.art.height >= (width === 360 ? 95 : 119));
        if (width === 360 && stage <= 2)
          assert(
            m.first.top < 800,
            `stage ${stage}: first content ${m.first.top}`,
          );
        if (width === 360) assert(m.compact.every((r) => r.height <= 46));
        if (out)
          await page.screenshot({
            path: `${out}/step${stage}-${width}.jpg`,
            type: "jpeg",
            quality: 80,
          });
        results.push({ width, stage, ...m });
      };
      await measure(1);
      await page.locator('[data-tour-target="signup-pool"]').click();
      await page.locator(".account-select input").first().waitFor();
      await page.waitForTimeout(150);
      await measure(2);
      const unobscured = await page.evaluate(() => {
        const name = document
          .querySelector(".account-list .signed-up-name")
          .getBoundingClientRect();
        const bar = document
          .querySelector(".signup-flow .submit-bar")
          .getBoundingClientRect();
        return name.top >= 0 && name.bottom <= Math.min(innerHeight, bar.top);
      });
      assert(
        unobscured,
        "first account name must be visible above the sticky bar",
      );
      await page.locator(".account-select input").first().check();
      await page.locator(".submit-bar .primary").click();
      await page.locator(".signup-review").waitFor();
      await page.waitForTimeout(100);
      await measure(3);
      const selected = await page
        .locator(".signup-review .review-row small")
        .allTextContents();
      await page
        .getByRole("button", { name: "Change accounts", exact: true })
        .click();
      assert.equal(
        await page.locator(".account-select input:checked").count(),
        1,
      );
      await page.locator(".submit-bar .primary").click();
      await page
        .getByRole("button", { name: "Change CWL", exact: true })
        .click();
      await page.locator('[data-tour-target="signup-pool"]').click();
      await page.locator(".signup-review").waitFor();
      assert.deepEqual(
        await page
          .locator(".signup-review .review-row small")
          .allTextContents(),
        selected,
      );
      if (out)
        await page.screenshot({
          path: `${out}/review-change-${width}.jpg`,
          type: "jpeg",
          quality: 80,
        });
      if (width === 360)
        await page
          .getByRole("button", { name: "Open menu", exact: true })
          .click();
      await page.waitForTimeout(300);
      const height = await page
        .locator(".sidebar-foot")
        .evaluate((el) => el.getBoundingClientRect().height);
      assert(height <= 120, `footer height ${height}`);
      assert.equal(
        await page
          .locator(".sidebar-foot > button")
          .filter({ hasText: "Sign out" })
          .count(),
        0,
      );
      if (out)
        await page.screenshot({
          path: `${out}/sidebar-${width}.jpg`,
          type: "jpeg",
          quality: 80,
        });
      const profile = page.locator(".account-menu-profile-trigger");
      await profile.focus();
      await page.keyboard.press("Enter");
      await page.getByRole("menuitem", { name: "Sign out" }).waitFor();
      await page.keyboard.press("Escape");
      await page.locator(".account-menu-popover").waitFor({ state: "hidden" });
      assert(
        await profile.evaluate((el) => el === document.activeElement),
        "Escape restores profile focus",
      );
      if (width === 360) {
        assert.equal(
          await page
            .getByRole("button", { name: "Open menu", exact: true })
            .getAttribute("aria-expanded"),
          "true",
          "menu Escape keeps drawer open",
        );
        await page.keyboard.press("Escape");
        await page.locator(".account-menu-avatar-trigger").click();
        await page.getByRole("menuitem", { name: "Sign out" }).waitFor();
        await page.keyboard.press("Escape");
        await page
          .locator(".account-menu-popover")
          .waitFor({ state: "hidden" });
        assert(
          await page
            .locator(".account-menu-avatar-trigger")
            .evaluate((el) => el === document.activeElement),
        );
      }
      results.push({
        width,
        footerHeight: height,
        accountMenuKeyboard: "passed",
      });
      await page.close();
    }
    assert.deepEqual(errors, []);
    assert.deepEqual(writes, []);
    const state = await (await fetch(base + "/qa/state")).json();
    assert.deepEqual(state.current, state.baseline);
    console.log(
      JSON.stringify({ results, writes, counts: state.current }, null, 2),
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
