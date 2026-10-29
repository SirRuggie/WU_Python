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
        "prior-draft",
        "closed",
        "empty",
        "all-signed",
        "staff",
      ]) {
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
        await page.goto(base + "/");
        await page
          .getByRole("button", { name: "Open local test session" })
          .click();
        await page.locator(".tour-close").click();
        if (scenario === "prior-draft") {
          await page.goto(base + "/signup");
          await page.locator('[data-tour-target="signup-pool"]').click();
          await page.locator('[data-tour-target="signup-account"]').check();
        }
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
          (scenario === "closed"
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
        if (scenario === "finish" || scenario === "staff") {
          for (let i = 6; i < 13; i++) {
            await page.locator(".tour-next").click();
            await page.waitForTimeout(250);
          }
        } else await page.locator(".tour-close").click();
        await page.waitForTimeout(500);
        assert.equal(new URL(page.url()).pathname, initialPath);
        assert.deepEqual(await storage(), before);
        if (scenario === "prior-draft") {
          assert.equal(
            await page
              .locator('[data-tour-target="signup-account"]')
              .isChecked(),
            true,
          );
        } else if (["exit", "finish"].includes(scenario)) {
          await page.goto(base + "/signup");
          await page.locator('[data-tour-target="signup-pool"]').click();
          assert.equal(
            await page.locator(".account-select input:checked").count(),
            0,
          );
        }
        assert.deepEqual(writes, []);
        results.push({ width, scenario, pass: true });
        await page.close();
      }
    }
    console.log(JSON.stringify(results));
  } finally {
    await fetch(base + "/qa/scenario?season=1");
    await fetch(base + "/qa/member?member=1");
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
