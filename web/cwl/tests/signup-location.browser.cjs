/* Synthetic member fixture only. Read-only UI checks and navigation. */
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const port = Number(process.argv[2]);
assert(port >= 8900 && port <= 8999 && port !== 8767);
const base = `http://127.0.0.1:${port}`;
const out = path.resolve(__dirname, "../../../.local/p52-evidence");
fs.mkdirSync(out, { recursive: true });
(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    args: ["--no-sandbox"],
  });
  const results = [];
  try {
    for (const width of [360, 1440]) {
      const page = await browser.newPage({
        viewport: { width, height: width === 360 ? 800 : 1000 },
      });
      const errors = [],
        writes = [];
      page.on("pageerror", (e) => errors.push(String(e)));
      await page.addInitScript(() =>
        localStorage.setItem(
          "wu-member-tour-v1",
          JSON.stringify({ skips: 0, dismissed: true }),
        ),
      );
      await page.route("**/*", (route) =>
        new URL(route.request().url()).origin === base
          ? route.continue()
          : route.abort(),
      );
      await page.request.get(base + "/qa/scenario?season=1");
      await page.goto(base + "/my-signups");
      await page
        .getByRole("button", { name: "Open local test session" })
        .click();
      await page.locator(".member-signup-remaining").waitFor();
      page.on("request", (r) => {
        if (!["GET", "HEAD"].includes(r.method()))
          writes.push(r.method() + " " + r.url());
      });
      for (const [name, season, url] of [
        ["signups-open", 1, "/my-signups"],
        ["signups-closed", 2, "/my-signups"],
        ["assignments-published", 4, "/assignments"],
        ["assignments-unpublished", 1, "/assignments"],
      ]) {
        await page.request.get(base + "/qa/scenario?season=" + season);
        await page.goto(base + url);
        if (url === "/my-signups") {
          await page.locator(".member-signup-success").waitFor();
          if (season === 1)
            await page.locator(".member-signup-remaining").waitFor();
          assert.equal(
            await page.locator(".member-signup-remaining").count(),
            season === 1 ? 1 : 0,
          );
          assert.equal(
            await page
              .locator(".member-signup-summary")
              .getByRole("button", { name: "Change signups ›" })
              .count(),
            0,
          );
          assert.equal(
            await page.locator(".member-signup-success li").count(),
            2,
          );
          if (season === 2)
            assert.equal(
              await page.locator(".member-signup-summary button").count(),
              0,
            );
          assert(
            await page
              .locator(".member-signup-summary")
              .evaluate(
                (e) =>
                  !!(
                    e.compareDocumentPosition(
                      document.querySelector(".registered .section-heading"),
                    ) & Node.DOCUMENT_POSITION_FOLLOWING
                  ),
              ),
          );
        } else {
          await page
            .getByText(
              season === 4 ? "Published clan assignments" : "Not published yet",
              { exact: true },
            )
            .waitFor();
          assert.equal(
            await page
              .locator(".member-signup-success,.member-signup-remaining")
              .count(),
            0,
          );
          if (season === 4) {
            const box = await page
              .locator(".member-open-clan")
              .first()
              .boundingBox();
            assert(
              box.y >= 0 && box.y + box.height <= (width === 360 ? 800 : 1000),
              JSON.stringify(box),
            );
            results.push({ width, openClan: box });
          } else
            assert.match(
              await page.locator(".member-unpublished-status").innerText(),
              /My signups/,
            );
        }
        await page.evaluate(() => window.scrollTo(0, 0));
        assert.equal(
          await page.evaluate(
            () => document.documentElement.scrollWidth > innerWidth,
          ),
          false,
        );
        await page.screenshot({
          path: path.join(out, `${name}-${width}.png`),
          fullPage: true,
        });
      }
      await page.goto(base + "/my-signups");
      await page.locator(".member-signup-remaining button").click();
      await page.locator(".pool-choice-grid").waitFor();
      assert.equal(new URL(page.url()).pathname, "/signup");
      assert.deepEqual(errors, []);
      assert.deepEqual(writes, []);
      await page.close();
    }
    const state = await (await fetch(base + "/qa/state")).json();
    assert.deepEqual(state.current, state.baseline);
    fs.writeFileSync(
      path.join(out, "layout.json"),
      JSON.stringify(
        { results, counts: state.current, unchanged: true },
        null,
        2,
      ),
    );
    console.log(
      "Signup locations: open/closed/published/unpublished, 360/1440, no writes and counts unchanged",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
