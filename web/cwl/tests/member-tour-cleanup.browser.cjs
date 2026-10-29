const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const port = Number(process.argv[2] || 8975);
assert(port >= 8900 && port <= 8999);
const base = `http://127.0.0.1:${port}`;
(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    args: ["--no-sandbox"],
  });
  const results = [];
  try {
    for (const width of [360, 1440]) {
      for (const scenario of [
        "exit",
        "finish",
        "prior-exit",
        "prior-escape",
        "prior-skip",
        "prior-finish",
        "prior-back",
        "closed",
        "error",
        "empty",
        "all-signed",
        "staff",
      ]) {
        await fetch(base + "/qa/reset-signups");
        await fetch(
          base + "/qa/scenario?season=" + (scenario === "closed" ? 2 : 1),
        );
        await fetch(
          base +
            "/qa/member?member=" +
            (scenario === "empty" ? 4 : scenario === "all-signed" ? 2 : 1) +
            (scenario === "staff" ? "&staff=1" : ""),
        );
        const page = await browser.newPage({
          viewport: { width, height: width === 360 ? 800 : 1000 },
        });
        await page.route("**/*", (r) =>
          new URL(r.request().url()).origin === base ? r.continue() : r.abort(),
        );
        if (scenario === "error")
          await page.route("**/api/cwl/linked-accounts?*", (r) =>
            r.fulfill({
              status: 503,
              contentType: "application/json",
              body: JSON.stringify({ error: "Fixture account read failed" }),
            }),
          );
        await page.goto(base + "/");
        await page
          .getByRole("button", { name: "Open local test session" })
          .click();
        await page.locator(".tour-close").click();
        const navigateSignup = async () => {
          await page
            .locator('.sidebar [data-tour-target="register"]')
            .evaluate((el) => el.click());
          await page.waitForTimeout(250);
        };
        if (scenario.startsWith("prior-")) {
          await navigateSignup();
          await page.getByRole("button", { name: /Main CWL/ }).click();
          await page.locator(".account-select input").nth(1).check();
        }
        const priorTags = await page
          .locator(".account-select:has(input:checked) small")
          .allTextContents();
        const initialHistory = await page.evaluate(() => history.length);
        const initialPath = new URL(page.url()).pathname;
        const storage = () =>
          page.evaluate(() => ({
            local: Object.fromEntries(
              Object.entries(localStorage).filter(
                ([k]) =>
                  !k.startsWith("wu-member-tour") &&
                  !k.startsWith("wu-snapshot-v1:"),
              ),
            ),
            session: Object.fromEntries(
              Object.entries(sessionStorage).filter(
                ([k]) =>
                  !k.startsWith("wu-member-tour") &&
                  !k.startsWith("wu-snapshot-v1:"),
              ),
            ),
          }));
        const before = await storage();
        const writes = [];
        page.on("request", (r) => {
          if (r.method() !== "GET") writes.push(r.method() + " " + r.url());
        });
        await page.locator(".tour-launcher").evaluate((el) => el.click());
        for (
          let i = 0;
          i <
          (scenario === "prior-skip"
            ? 0
            : ["closed", "error"].includes(scenario)
              ? 3
              : scenario === "empty" || scenario === "all-signed"
                ? 5
                : 6);
          i++
        ) {
          await page.locator(".tour-next").click();
          await page.waitForTimeout(200);
          await page.locator(".tour-next:enabled").waitFor();
        }
        if (scenario === "closed")
          assert.match(
            await page.locator(".tour-copy").innerText(),
            /Signups are closed right now/,
          );
        if (scenario === "error") {
          assert.match(
            await page.locator(".tour-copy").innerText(),
            /We couldn't load your accounts/,
          );
          assert.equal(await page.locator(".tour-next").isEnabled(), true);
        }
        if (scenario === "empty")
          assert.match(
            await page.locator(".tour-copy").innerText(),
            /Link your Clash account here first/,
          );
        if (scenario === "all-signed")
          assert.match(
            await page.locator(".tour-copy").innerText(),
            /All your accounts are already signed up/,
          );
        if (["finish", "staff", "prior-finish"].includes(scenario)) {
          for (let i = 6; i < 13; i++) {
            await page.locator(".tour-next").click();
            await page.waitForTimeout(250);
          }
        } else if (scenario === "prior-escape")
          await page.keyboard.press("Escape");
        else if (scenario === "prior-skip")
          await page.getByRole("button", { name: /Skip/ }).click();
        else if (scenario === "prior-back") await page.goBack();
        else await page.locator(".tour-close").click();
        await page.waitForTimeout(500);
        assert.equal(new URL(page.url()).pathname, initialPath, scenario);
        assert.deepEqual(await storage(), before);
        assert.equal(await page.evaluate(() => history.length), initialHistory);
        if (scenario.startsWith("prior-")) {
          await navigateSignup();
          assert.deepEqual(
            await page
              .locator(".account-select:has(input:checked) small")
              .allTextContents(),
            priorTags,
          );
          assert.match(
            await page
              .locator(".signup-flow .section-heading .eyebrow")
              .innerText(),
            /Main/i,
          );
        } else if (["exit", "finish"].includes(scenario)) {
          await navigateSignup();
          await page.locator('[data-tour-target="signup-pool"]').click();
          assert.equal(
            await page.locator(".account-select input:checked").count(),
            0,
          );
        }
        if (scenario === "prior-back") {
          // The signup draft is deliberately dirty: allow the normal leave prompt.
          page.on("dialog", (dialog) => dialog.accept());
          await page.goBack();
          await page.waitForTimeout(300);
          assert.equal(
            new URL(page.url()).pathname,
            "/",
            "Back preserves Home",
          );
          await page.goForward();
          await page.waitForTimeout(300);
          assert.equal(
            new URL(page.url()).pathname,
            "/signup",
            "Forward returns once",
          );
          assert.equal(
            await page.evaluate(() => history.length),
            initialHistory,
          );
        }
        assert.deepEqual(writes, []);
        let submitted = 0;
        if (["exit", "finish"].includes(scenario)) {
          await page.locator(".account-select input").first().check();
          await page.locator(".submit-bar .primary").click();
          const response = page.waitForResponse(
            (r) =>
              r.request().method() === "POST" &&
              /\/seasons\/1\/signups$/.test(r.url()),
          );
          await page.locator('[data-tour-target="signup-confirm"]').click();
          assert.equal((await response).status(), 200);
          assert.equal(writes.length, 1);
          assert.match(writes[0], /POST .*\/seasons\/1\/signups$/);
          submitted = 1;
        }
        results.push({
          width,
          scenario,
          pass: true,
          fixtureSignupPosts: submitted,
        });
        await page.close();
      }
    }
    console.log(JSON.stringify(results));
  } finally {
    await fetch(base + "/qa/reset-signups");
    const state = await (await fetch(base + "/qa/state")).json();
    assert.deepEqual(
      state.current,
      state.baseline,
      "fixture signups, assignments and locks restored after four explicit signup POSTs",
    );
    await fetch(base + "/qa/scenario?season=1");
    await fetch(base + "/qa/member?member=1");
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
