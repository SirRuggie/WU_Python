const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const origin =
  "http://127.0.0.1:" +
  fs
    .readFileSync(
      path.resolve(__dirname, "../../../.local/p93-preview-port"),
      "utf8",
    )
    .trim();
const out = path.resolve(__dirname, "../../../.local/p93-bulk-layout");
fs.mkdirSync(out, { recursive: true });
(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox"],
  });
  const results = [];
  try {
    for (const width of [320, 360, 390, 1440]) {
      const page = await browser.newPage({ viewport: { width, height: 1000 } });
      const posts = [],
        errors = [];
      page.on("request", (r) => {
        if (r.method() === "POST" && r.url().includes("/manage/members/"))
          posts.push({
            path: new URL(r.url()).pathname,
            body: r.postDataJSON(),
          });
      });
      page.on("pageerror", (e) => errors.push(e.message));
      await page.route("**/*", (r) =>
        new URL(r.request().url()).origin === origin ? r.continue() : r.abort(),
      );
      await page.goto(origin + "/server/members");
      await page
        .getByRole("button", { name: /Open local test session/i })
        .click();
      await page.locator(".members-person").first().waitFor();
      const selected = await page
        .locator(".members-person")
        .evaluateAll((rows) =>
          rows.slice(0, 2).map((row) => row.dataset.memberId),
        );
      await page.locator(".members-person input").nth(0).check();
      await page.locator(".members-person input").nth(1).check();
      const bar = page.getByRole("region", {
        name: "Selected people",
        exact: true,
      });
      await bar.waitFor();
      assert.equal(
        await bar.evaluate((e) => getComputedStyle(e).position),
        "sticky",
      );
      await page
        .getByPlaceholder("Name, nickname, username or Discord ID")
        .fill("Cedar");
      await bar
        .getByRole("button", { name: "2 selected · 2 hidden", exact: true })
        .waitFor();
      await bar
        .getByRole("button", { name: "2 selected · 2 hidden", exact: true })
        .click();
      assert.equal(await page.locator(".members-person").count(), 2);
      await bar.getByRole("button", { name: "Add role", exact: true }).click();
      let dialog = page.locator("dialog.confirm-dialog[open]").last();
      await dialog
        .getByRole("combobox", { name: "Roles", exact: true })
        .selectOption("333333333333333331");
      await dialog
        .getByRole("button", { name: "Review changes", exact: true })
        .click();
      await page
        .getByText("Add Fixture role 1 to 2 members", { exact: true })
        .waitFor();
      assert(
        !posts.some((r) => r.path.endsWith("/role-confirm")),
        "Bulk work started before confirmation",
      );
      dialog = page.locator("dialog.confirm-dialog[open]").last();
      await dialog
        .getByRole("button", { name: "Add role", exact: true })
        .click();
      await page
        .getByRole("button", { name: "Stop run", exact: true })
        .waitFor();
      const preview = posts.find((r) => r.path.endsWith("/role-preview"));
      const confirm = posts.find((r) => r.path.endsWith("/role-confirm"));
      assert.deepEqual(
        [...preview.body.member_ids].sort(),
        [...selected].sort(),
      );
      assert.deepEqual([...confirm.body.selected].sort(), [...selected].sort());
      assert.equal(
        posts.filter((r) => r.path.endsWith("/role-confirm")).length,
        1,
      );
      await page.getByRole("button", { name: "Stop run", exact: true }).click();
      await page.getByText("Role changes · Stopped", { exact: true }).waitFor();
      assert.equal(posts.filter((r) => r.path.endsWith("/stop")).length, 1);
      assert.deepEqual(errors, []);
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      );
      await page.screenshot({
        path: path.join(out, "bulk-" + width + ".png"),
        fullPage: true,
      });
      results.push({
        width,
        selected: 2,
        hidden: 2,
        exactSentIds: true,
        confirmation: true,
        stop: true,
        errors,
      });
      await page.close();
    }
    fs.writeFileSync(
      path.join(out, "results.json"),
      JSON.stringify(results, null, 2),
    );
    console.log(
      "Four hidden-inclusive bulk confirmation/Stop/sticky cases pass",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
