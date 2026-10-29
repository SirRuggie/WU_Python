/* Isolated member_signup.py fixture only; no signup mutations. */
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const port = Number(process.argv[2] || 8972);
assert(port >= 8900 && port <= 8999);
const base = `http://127.0.0.1:${port}`;

(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    args: ["--no-sandbox"],
  });
  const results = [];
  try {
    for (const width of [320, 360, 1440]) {
      const page = await browser.newPage({
        viewport: { width, height: width === 1440 ? 1000 : 800 },
      });
      const errors = [];
      page.on("pageerror", (error) => errors.push(String(error)));
      await page.route("**/*", (route) =>
        new URL(route.request().url()).origin === base
          ? route.continue()
          : route.abort(),
      );
      await page.goto(base + "/my-signups");
      await page
        .getByRole("button", { name: "Open local test session" })
        .click();
      await page.getByText("Your saved CWL signups for this season.").waitFor();
      assert.equal(await page.title(), "My signups · Warriors United");
      const layout = await page
        .locator(".member-step-strip")
        .evaluate((nav) => {
          const rows = [...nav.querySelectorAll("button")].map((button) => {
            const range = document.createRange();
            range.selectNodeContents(button);
            const rect = button.getBoundingClientRect();
            return {
              lines: range.getClientRects().length,
              top: rect.top,
              height: rect.height,
              overflow: button.scrollWidth > button.clientWidth,
            };
          });
          return {
            rows,
            overflow: document.documentElement.scrollWidth > innerWidth,
          };
        });
      assert(!layout.overflow);
      assert(
        layout.rows.every(
          (row) => row.lines === 1 && !row.overflow && row.height >= 44,
        ),
      );
      assert(layout.rows.every((row) => row.top === layout.rows[0].top));
      await page.goto(base + "/");
      await page.locator(".member-signup-success").waitFor();
      assert.equal(await page.locator(".member-signup-refresh").count(), 0);
      if (width === 360) {
        await page.request.get(base + "/qa/scenario?season=4");
        await page.goto(base + "/assignments");
        await page
          .getByText("Published clan assignments", { exact: true })
          .waitFor();
        assert.equal(
          await page
            .getByRole("button", { name: "Refresh", exact: true })
            .count(),
          1,
        );
        await page.request.get(base + "/qa/scenario?season=1");
        await page.goto(base + "/assignments");
        await page
          .getByRole("button", { name: "Sign up 3 more accounts ›", exact: true })
          .click();
        await page.getByRole("button", { name: /Main Clan CWL/ }).click();
        await page.locator(".account-select").first().waitFor();
        assert.equal(
          await page.locator(".account-select input:checked").count(),
          0,
        );
      }
      assert.deepEqual(errors, []);
      results.push({ width, ...layout });
      await page.close();
    }
    console.log(JSON.stringify(results, null, 2));
    const state = await (await fetch(base + "/qa/state")).json();
    assert.deepEqual(state.current, state.baseline);
    assert.deepEqual(
      state.requests.filter(
        (row) => row.method !== "GET" && !row.path.endsWith("/dev/login"),
      ),
      [],
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
