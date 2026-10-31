const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const port = Number(process.argv[2]);
assert(port > 0 && port <= 65535 && port !== 8767);
const base = `http://127.0.0.1:${port}`,
  out = process.env.WU_POLISH_EVIDENCE || "/tmp/wu-announcement-polish";
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
    await page.locator(".announcement-pool-card").first().waitFor();
    fs.mkdirSync(out, { recursive: true });
    for (const card of await page.locator(".announcement-pool-card").all()) {
      for (const label of ["Preview", "Edit", "Clear", "Test full post"]) {
        assert.equal(await card.getByRole("button", { name: label, exact: true }).isVisible(), false, label + " visible at rest");
      }
    }
    await page.screenshot({ path: `${out}/360-at-rest.png` });
    const before = await (
      await context.request.get(base + "/api/cwl/seasons/1/manage-bridge")
    ).json();
    assert(
      !Object.values(before.pools).some((p) => p.delivery?.status === "sent"),
      "tests consumed production state",
    );
    await page.getByRole("button", { name: "Review both pools" }).click();
    await page
      .getByRole("button", { name: "Queue both announcements" })
      .click();
    for (const name of ["main-cwl", "lazy-cwl"]) {
      const done = page
        .getByRole("dialog")
        .filter({
          has: page.getByRole("heading", { name: "Done", exact: true }),
        });
      await done.waitFor({ timeout: 90000 });
      assert.match(await done.textContent(), new RegExp(name));
      assert.equal(await done.getByRole("button").count(), 1);
      assert.equal(
        await done.getByRole("link", { name: "Open in Discord" }).count(),
        1,
      );
      await page.screenshot({ path: `${out}/360-${name}-done.png` });
      await done.getByRole("button", { name: "Close" }).click();
    }
    const state = await (
      await context.request.get(base + "/qa/sequence")
    ).json();
    assert.equal(state.posts.length, 12);
    assert.deepEqual(errors, []);
    fs.writeFileSync(
      out + "/production-payloads.json",
      JSON.stringify(state, null, 2),
    );
    console.log(
      JSON.stringify({
        messages: state.posts.length,
        completedPools: 2,
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
