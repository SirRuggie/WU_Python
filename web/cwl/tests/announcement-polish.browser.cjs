const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const port = Number(process.argv[2]);
assert(port >= 8900 && port <= 8999);
const base = `http://127.0.0.1:${port}`;
const out = process.env.WU_POLISH_EVIDENCE || "/tmp/wu-announcement-polish";
fs.mkdirSync(out, { recursive: true });
(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    args: ["--no-sandbox"],
  });
  try {
    const context = await browser.newContext({
      viewport: { width: 360, height: 800 },
    });
    await context.route("**/*", (r) =>
      new URL(r.request().url()).origin === base ? r.continue() : r.abort(),
    );
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(base + "/?view=publication&step=announce&season=1");
    await page.getByRole("button", { name: "Open local test session" }).click();
    const cards = page.locator(".announcement-pool-card");
    await cards.first().waitFor();
    for (const width of [360, 1440]) {
      await page.setViewportSize({ width, height: width === 360 ? 800 : 1000 });
      await cards.first().scrollIntoViewIfNeeded();
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        "page overflow",
      );
      if (!process.env.WU_POLISH_BEFORE) {
        for (const card of await cards.all()) {
          assert(
            (await card.boundingBox()).height < 800,
            "pool taller than phone screen",
          );
          assert.equal(
            await card
              .getByRole("button", { name: "Review and send", exact: true })
              .count(),
            1,
          );
          assert.equal(
            await card
              .getByRole("button", { name: "Preview", exact: true })
              .isVisible(),
            false,
          );
        }
      }
      await page.screenshot({
        path: `${out}/${width}-${process.env.WU_POLISH_BEFORE ? "before" : "after"}-rest.png`,
        fullPage: true,
      });
    }
    if (process.env.WU_POLISH_BEFORE) return;
    await page.setViewportSize({ width: 360, height: 800 });
    const main = cards.first();
    await main
      .locator("summary")
      .filter({ hasText: /^More$/ })
      .click();
    await main.getByText("Test full post · no pings", { exact: true }).click();
    const combo = main.getByRole("combobox", { name: "Full test channel" });
    await combo.fill("staff-tests");
    await main.getByRole("option").first().click();
    await main.getByLabel("Make this the default").check();
    await main
      .getByRole("button", { name: "Test full post", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Send full test", exact: true })
      .click();
    await page
      .getByRole("dialog")
      .filter({ has: page.getByRole("heading", { name: "Done", exact: true }) })
      .waitFor({ timeout: 90000 });
    const dialog = page.getByRole("dialog");
    assert.equal(await dialog.getByRole("button").count(), 1);
    assert.match(await dialog.textContent(), /TEST posted to #staff-tests/);
    assert.equal(
      await dialog.getByRole("link", { name: "Open in Discord" }).count(),
      1,
    );
    await page.screenshot({ path: `${out}/360-test-done.png` });
    await dialog.getByRole("button", { name: "Close" }).click();
    const saved = await (
      await context.request.get(
        base + "/api/cwl/manage/announcement-test-channel",
      )
    ).json();
    assert.equal(saved.channel_id, "333333333333333333");
    assert.equal(saved.revision, 1);
    await page.reload();
    await cards.first().waitFor();
    await cards
      .first()
      .locator("summary")
      .filter({ hasText: /^More$/ })
      .click();
    await cards
      .first()
      .getByText("Test full post · no pings", { exact: true })
      .click();
    assert.match(
      await cards
        .first()
        .getByRole("combobox", { name: "Full test channel" })
        .inputValue(),
      /staff-tests/,
    );
    const state = await (
      await context.request.get(base + "/qa/sequence")
    ).json();
    for (const post of state.posts) {
      assert.deepEqual(post.payload.allowed_mentions, { parse: [], roles: [] });
      assert(!JSON.stringify(post.payload).includes("TEST"));
    }
    assert.equal(state.posts.length, 6);
    fs.writeFileSync(
      out + "/test-payloads.json",
      JSON.stringify(state, null, 2),
    );
    assert.deepEqual(errors, []);
    console.log(
      JSON.stringify({
        widths: [360, 1440],
        testMessages: state.posts.length,
        savedRevision: saved.revision,
        errors,
      }),
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
